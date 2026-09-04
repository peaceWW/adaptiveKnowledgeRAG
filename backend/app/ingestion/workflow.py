from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import DocumentStatus, KnowledgeType, RelationType
from app.domain.registry import registry
from app.domain.strategy import DocumentContext
from app.ingestion.classifier import KnowledgeClassifier
from app.ingestion.parser import parse_bytes
from app.ingestion.validator import validate_draft
from app.model_gateway.gateway import ModelGateway
from app.storage.minio_store import MinioStore
from app.storage.models import Document, KnowledgeRelation, KnowledgeUnit, ReviewTask
from app.storage.qdrant_store import QdrantStore


class IngestState(TypedDict, total=False):
    document_id: str
    filename: str
    raw: bytes
    text: str
    structure: dict[str, Any]
    classification: dict[str, Any]
    confirmed_strategy: str
    unit_ids: list[str]
    status: str
    error: str


class IngestionWorkflow:
    def __init__(
        self,
        session: AsyncSession,
        gateway: ModelGateway,
        minio: MinioStore,
        qdrant: QdrantStore,
        es_store=None,
        neo4j_store=None,
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.minio = minio
        self.qdrant = qdrant
        self.es_store = es_store
        self.neo4j_store = neo4j_store
        self.classifier = KnowledgeClassifier(gateway)
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(IngestState)
        graph.add_node("parse", self.parse)
        graph.add_node("classify", self.classify)
        graph.add_node("extract", self.extract)
        graph.add_node("index", self.index_units)
        graph.add_edge(START, "parse")
        graph.add_edge("parse", "classify")
        graph.add_conditional_edges(
            "classify",
            self._route_after_classify,
            {"wait": END, "extract": "extract"},
        )
        graph.add_edge("extract", "index")
        graph.add_edge("index", END)
        return graph.compile()

    def _route_after_classify(self, state: IngestState) -> str:
        if state.get("confirmed_strategy"):
            return "extract"
        return "wait"

    async def parse(self, state: IngestState) -> IngestState:
        parsed = parse_bytes(state["filename"], state["raw"])
        doc = await self.session.get(Document, state["document_id"])
        if doc:
            doc.status = DocumentStatus.PARSING.value
            doc.parse_progress = 40
            doc.structure = {
                "chapters": parsed.get("chapters") or [],
                "pages": [
                    {"page": p["page"], "text": (p.get("text") or "")[:4000]}
                    for p in parsed.get("pages") or []
                ],
            }
            await self.session.commit()
        return {**state, "text": parsed["text"], "structure": parsed, "status": "parsed"}

    async def classify(self, state: IngestState) -> IngestState:
        classification = self.classifier.classify(state.get("text") or "", state["filename"])
        doc = await self.session.get(Document, state["document_id"])
        recommended = {
            KnowledgeType.INCIDENT_CASE.value: "Incident Case V1",
            KnowledgeType.API_DOCUMENT.value: "API Document V1",
        }.get(classification["knowledge_type"], "Technical Knowledge V1")
        if doc:
            doc.status = DocumentStatus.AWAITING_STRATEGY.value
            doc.parse_progress = 100
            doc.classification = classification
            doc.recommended_strategy = recommended
            await self.session.commit()
        return {
            **state,
            "classification": classification,
            "status": "awaiting_strategy",
        }

    async def extract(self, state: IngestState) -> IngestState:
        doc = await self.session.get(Document, state["document_id"])
        if not doc:
            return {**state, "error": "document missing", "status": "failed"}
        knowledge_type = (state.get("classification") or {}).get(
            "knowledge_type", KnowledgeType.TECHNICAL_CONCEPT.value
        )
        strategy = registry.get(knowledge_type)
        context = DocumentContext(
            document_id=doc.id,
            filename=doc.filename,
            text=state.get("text") or "",
            structure=state.get("structure") or doc.structure,
            classification=state.get("classification") or doc.classification,
        )
        drafts = strategy.build_units(context)
        unit_ids: list[str] = []
        doc.status = DocumentStatus.EXTRACTING.value
        doc.parse_progress = 85
        for draft in drafts:
            lifecycle, need_review = validate_draft(draft)
            unit = KnowledgeUnit(
                kb_id=doc.kb_id,
                document_id=doc.id,
                knowledge_type=draft.knowledge_type.value,
                title=draft.title,
                content=draft.content,
                semantic_role=draft.semantic_role.value,
                importance=draft.importance,
                domain="semiconductor",
                concepts=draft.concepts,
                parent_context=draft.parent_context,
                source_chapter=draft.source_chapter,
                source_section=draft.source_section,
                source_page=draft.source_page,
                source_span=draft.source_span,
                confidence=draft.confidence,
                lifecycle=lifecycle.value,
            )
            self.session.add(unit)
            await self.session.flush()
            unit_ids.append(unit.id)
            if need_review:
                self.session.add(
                    ReviewTask(ku_id=unit.id, document_id=doc.id, status="pending")
                )
            for concept in draft.concepts:
                self.session.add(
                    KnowledgeRelation(
                        from_id=unit.id,
                        to_id=concept,
                        relation_type=RelationType.RELATED_TO.value,
                        to_kind="concept",
                    )
                )
        await self.session.commit()
        return {**state, "unit_ids": unit_ids, "status": "extracted"}

    async def index_units(self, state: IngestState) -> IngestState:
        unit_ids = state.get("unit_ids") or []
        texts: list[str] = []
        units: list[KnowledgeUnit] = []
        for unit_id in unit_ids:
            unit = await self.session.get(KnowledgeUnit, unit_id)
            if not unit:
                continue
            units.append(unit)
            texts.append(f"{unit.title}\n{unit.content}")
        if texts:
            vectors = self.gateway.embed(texts)
            for unit, vector in zip(units, vectors, strict=False):
                payload = {
                    "kb_id": unit.kb_id,
                    "knowledge_type": unit.knowledge_type,
                    "semantic_role": unit.semantic_role,
                    "domain": unit.domain,
                    "concept_ids": unit.concepts,
                    "parent_id": unit.parent_id,
                    "source_level": unit.source_level,
                    "lifecycle": unit.lifecycle,
                    "version": unit.version,
                    "title": unit.title,
                    "content": unit.content[:2000],
                }
                self.qdrant.upsert(unit.id, vector, payload)
                if self.es_store:
                    await self.es_store.upsert(
                        unit.id,
                        {
                            "title": unit.title,
                            "content": unit.content,
                            "concepts": unit.concepts,
                            "semantic_role": unit.semantic_role,
                            "kb_id": unit.kb_id,
                            "lifecycle": unit.lifecycle,
                            "knowledge_type": unit.knowledge_type,
                            "domain": unit.domain,
                        },
                    )
                if self.neo4j_store:
                    self.neo4j_store.upsert_unit(
                        {
                            "id": unit.id,
                            "title": unit.title,
                            "semantic_role": unit.semantic_role,
                            "domain": unit.domain,
                            "kb_id": unit.kb_id,
                            "lifecycle": unit.lifecycle,
                            "concepts": unit.concepts or ["unknown"],
                        }
                    )
        doc = await self.session.get(Document, state["document_id"])
        if doc:
            doc.status = DocumentStatus.REVIEW.value
            doc.parse_progress = 100
            await self.session.commit()
            from app.retrieval.doc_index import ensure_document_index

            await ensure_document_index(self.session, doc, self.es_store, force=True)
        return {**state, "status": "indexed"}

    async def run_analyze(self, document_id: str, filename: str, raw: bytes) -> IngestState:
        return await self.graph.ainvoke(
            {
                "document_id": document_id,
                "filename": filename,
                "raw": raw,
                "confirmed_strategy": "",
            }
        )

    async def run_extract(self, document_id: str, filename: str, raw: bytes, strategy_type: str) -> IngestState:
        doc = await self.session.get(Document, document_id)
        structure = (doc.structure if doc else {}) or {}
        text = "\n".join(p.get("text") or "" for p in structure.get("pages") or [])
        if not text:
            parsed = parse_bytes(filename, raw)
            text = parsed["text"]
            structure = parsed
        return await self.graph.ainvoke(
            {
                "document_id": document_id,
                "filename": filename,
                "raw": raw,
                "text": text,
                "structure": structure,
                "classification": {"knowledge_type": strategy_type},
                "confirmed_strategy": strategy_type,
            }
        )
