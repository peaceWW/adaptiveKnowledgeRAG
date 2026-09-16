# 知识入库 LangGraph：parse → classify →（确认策略后）extract → index。
# 负责把 PDF/文本变成 Knowledge Unit，并写入 SQL / 向量 / 关键字 / 图谱。
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import DocumentStatus, KnowledgeType, RelationType
from app.domain.payload import unit_embed_text, unit_vector_payload
from app.domain.registry import registry
from app.domain.strategy import DocumentContext
from app.ingestion.assets import materialize_paper_assets
from app.ingestion.classifier import KnowledgeClassifier
from app.ingestion.coverage import apply_coverage_stubs
from app.ingestion.configured_extraction import build_configured_units, effective_snapshot, scoped_structure
from app.domain.extraction_policy import EXTRACTION_KINDS, extraction_kind
from app.ingestion.doc_annotator import annotate_document_index
from app.ingestion.parser import parse_bytes
from app.ingestion.validator import validate_draft
from app.model_gateway.gateway import ModelGateway
from app.observability.pipeline_log import draft_digest, step as pipeline_step, structure_digest
from app.retrieval.doc_index import merge_keyword_lists
from app.storage.minio_store import MinioStore
from app.storage.models import Document, KnowledgeRelation, KnowledgeUnit, ReviewTask
from app.storage.qdrant_store import QdrantStore


class IngestState(TypedDict, total=False):
    """图节点之间传递的入库状态；raw 仅在当次请求内存中，不落库。"""

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
    """文档分析与抽取编排器。图在构造时编译；存储依赖可降级（无 ES/Neo4j 时跳过对应写入）。"""

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
        """编译 parse→classify→extract→index；未确认策略时 classify 后结束，等待人工选 Strategy。"""
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
        """上传分析只到 classify；确认策略后的二次 invoke 才带 confirmed_strategy 进入 extract。"""
        if state.get("confirmed_strategy"):
            route = "extract"
        else:
            route = "wait"
        pipeline_step(
            "ingest",
            "route_after_classify",
            inputs={"document_id": state.get("document_id"), "confirmed_strategy": state.get("confirmed_strategy") or ""},
            result={"next": route},
        )
        return route

    async def parse(self, state: IngestState) -> IngestState:
        """解析 bytes 为 structure（页/章节/图公式清单），写回 Document，并保留已有 process_config。"""
        parsed = parse_bytes(state["filename"], state["raw"])
        doc = await self.session.get(Document, state["document_id"])
        if doc:
            doc.status = DocumentStatus.PARSING.value
            doc.parse_progress = 40
            process_config = ((doc.structure or {}).get("process_config") if doc.structure else None) or {}
            structure = dict(parsed)
            if process_config:
                structure["process_config"] = process_config
            doc.structure = structure
            meta = parsed.get("metadata") or {}
            if meta:
                doc.index_meta = {**(doc.index_meta or {}), **{key: value for key, value in meta.items() if value not in (None, "", [])}}
                keywords = meta.get("keywords") or []
                if keywords:
                    doc.index_keywords = merge_keyword_lists(doc.index_keywords, keywords)
            # 千问文档级标注：与解析出的 Index Terms 合并，人工 source=manual 仍优先
            llm_meta, llm_keywords = annotate_document_index(
                self.gateway,
                doc.filename,
                parsed.get("text") or "",
                doc.index_meta or {},
            )
            if llm_meta:
                doc.index_meta = {**(doc.index_meta or {}), **llm_meta}
            if llm_keywords:
                doc.index_keywords = merge_keyword_lists(doc.index_keywords, llm_keywords)
            await self.session.commit()
        pipeline_step(
            "ingest",
            "parse_node",
            inputs={"document_id": state["document_id"], "filename": state["filename"], "bytes": len(state.get("raw") or b"")},
            result=structure_digest(parsed),
        )
        return {**state, "text": parsed["text"], "structure": parsed, "status": "parsed"}

    async def classify(self, state: IngestState) -> IngestState:
        """识别 knowledge_type 与 document_genre，推荐 Strategy；文档进入 awaiting_strategy 待确认。"""
        classification = self.classifier.classify(
            state.get("text") or "",
            state["filename"],
            structure=state.get("structure"),
        )
        confirmed = state.get("confirmed_strategy") or ""
        if confirmed:
            try:
                classification["knowledge_type"] = KnowledgeType(confirmed).value
            except ValueError:
                pass
        if (state.get("structure") or {}).get("genre") == "academic_paper":
            classification["document_genre"] = "academic_paper"
        doc = await self.session.get(Document, state["document_id"])
        recommended = {
            KnowledgeType.INCIDENT_CASE.value: "Incident Case V1",
            KnowledgeType.API_DOCUMENT.value: "API Document V1",
        }.get(classification["knowledge_type"], "Technical Knowledge V1")
        if doc:
            previous = dict(doc.classification or {})
            if previous.get("coverage"):
                classification["coverage"] = previous["coverage"]
            doc.status = DocumentStatus.AWAITING_STRATEGY.value
            doc.parse_progress = 100
            doc.classification = classification
            doc.recommended_strategy = recommended
            if classification.get("knowledge_type"):
                merged_meta = dict(doc.index_meta or {})
                merged_meta["knowledge_type"] = classification["knowledge_type"]
                doc.index_meta = merged_meta
            await self.session.commit()
        pipeline_step(
            "ingest",
            "classify_node",
            inputs={
                "document_id": state["document_id"],
                "filename": state["filename"],
                "confirmed_strategy": confirmed,
                "parse_genre": (state.get("structure") or {}).get("genre"),
            },
            result={
                "knowledge_type": classification.get("knowledge_type"),
                "document_genre": classification.get("document_genre"),
                "confidence": classification.get("confidence"),
                "reason": classification.get("reason"),
                "recommended_strategy": recommended,
                "status": "awaiting_strategy",
            },
        )
        return {
            **state,
            "classification": classification,
            "status": "awaiting_strategy",
        }

    async def extract(self, state: IngestState) -> IngestState:
        """按 Strategy 抽 Knowledge Unit：裁剪图/公式入 MinIO，落库并解析 parent/关系，覆盖不足则进审核。"""
        doc = await self.session.get(Document, state["document_id"])
        if not doc:
            return {**state, "error": "document missing", "status": "failed"}
        knowledge_type = (state.get("classification") or {}).get(
            "knowledge_type", KnowledgeType.TECHNICAL_CONCEPT.value
        )
        strategy = registry.get(knowledge_type)
        structure = state.get("structure") or doc.structure or {}
        snapshot = effective_snapshot(
            doc.structure or structure,
            knowledge_type,
            fallback_roles=list((state.get("classification") or {}).get("roles") or []),
        )
        structure = scoped_structure(structure, snapshot)
        # 论文图/公式必须先有 PNG，后续 Vision 与回答引用才拿得到 image_key
        if state.get("raw"):
            structure = materialize_paper_assets(self.minio, doc.id, state.get("raw") or b"", dict(structure))
            merged = dict(doc.structure or {})
            # Do not erase the analyzed inventory for intentionally disabled modalities.
            selected_policy = snapshot.get("extraction_policy") or {}
            for key, value in structure.items():
                policy_key = {"equations": "formulas", "figures": "images", "tables": "tables", "citations": "references"}.get(key)
                if not policy_key or selected_policy.get(policy_key, True):
                    merged[key] = value
            doc.structure = merged
            pipeline_step(
                "ingest",
                "assets",
                inputs={"document_id": doc.id, "filename": doc.filename},
                result={
                    "figures_with_png": sum(1 for item in (structure.get("figures") or []) if item.get("image_key")),
                    "equations_with_png": sum(1 for item in (structure.get("equations") or []) if item.get("image_key")),
                    "tables_with_png": sum(1 for item in (structure.get("tables") or []) if item.get("image_key")),
                    "figure_keys": [item.get("image_key") for item in (structure.get("figures") or []) if item.get("image_key")],
                    "equation_keys": [item.get("image_key") for item in (structure.get("equations") or []) if item.get("image_key")],
                },
            )
        classification = state.get("classification") or doc.classification or {}
        context = DocumentContext(
            document_id=doc.id,
            filename=doc.filename,
            text=state.get("text") or "",
            structure=structure,
            classification=classification,
            gateway=self.gateway,
            raw=state.get("raw"),
            minio=self.minio,
            extraction_policy=snapshot.get("extraction_policy") or {},
        )
        drafts = build_configured_units(context, snapshot)
        drafts, coverage = apply_coverage_stubs(structure, drafts, KnowledgeType(snapshot["knowledge_type"]))
        merged = dict(doc.structure or {})
        merged["extraction_summary"] = {
            item["key"]: sum(extraction_kind(draft) == item["key"] for draft in drafts) for item in EXTRACTION_KINDS
        }
        merged["applied_snapshot"] = {
            "id": snapshot.get("id"),
            "name": snapshot.get("name"),
            "chunk_policy": snapshot.get("chunk_policy"),
            "extraction_policy": snapshot.get("extraction_policy"),
        }
        doc.structure = merged
        pipeline_step(
            "ingest",
            "extract",
            inputs={
                "document_id": doc.id,
                "filename": doc.filename,
                "knowledge_type": snapshot.get("knowledge_type") or knowledge_type,
                "strategy": snapshot.get("name") or strategy.__class__.__name__,
                "chunk_policy": snapshot.get("chunk_policy"),
                "extraction_policy": snapshot.get("extraction_policy"),
                "process_config": (structure.get("process_config") or {}),
            },
            result={
                **draft_digest(drafts),
                "coverage_complete": coverage.get("complete"),
                "coverage_score": coverage.get("score"),
                "retrieval_ready_score": coverage.get("retrieval_ready_score"),
                "missing_equations": coverage.get("missing_equations"),
                "missing_figures": coverage.get("missing_figures"),
                "missing_roles": coverage.get("missing_roles"),
            },
        )
        classification = dict(classification)
        classification["coverage"] = coverage
        doc.classification = classification
        await self._purge_document_knowledge(doc.id)
        unit_ids: list[str] = []
        doc.status = DocumentStatus.EXTRACTING.value
        doc.parse_progress = 85
        pending: list[tuple[str, object]] = []
        anchor_to_id: dict[str, str] = {}
        coverage_review = not coverage.get("complete", True)
        for draft in drafts:
            lifecycle, need_review = validate_draft(draft)
            if coverage_review and (draft.unit_meta or {}).get("stub"):
                need_review = True
            unit = KnowledgeUnit(
                kb_id=doc.kb_id,
                document_id=doc.id,
                knowledge_type=draft.knowledge_type.value,
                title=draft.title,
                content=draft.content,
                semantic_role=draft.semantic_role.value,
                importance=draft.importance,
                domain="semiconductor",
                sub_domain=_sub_domain(structure),
                concepts=draft.concepts,
                parent_context=draft.parent_context[:500],
                source_chapter=(draft.source_chapter or "")[:64],
                source_section=(draft.source_section or "")[:64],
                source_page=draft.source_page,
                source_span=draft.source_span,
                unit_meta=draft.unit_meta or {},
                confidence=draft.confidence,
                lifecycle=lifecycle.value,
                source_level=draft.source_level or unit_source_level(draft),
            )
            self.session.add(unit)
            await self.session.flush()
            unit_ids.append(unit.id)
            anchor = str((draft.unit_meta or {}).get("anchor") or "")
            if anchor:
                anchor_to_id[anchor] = unit.id
            pending.append((unit.id, draft))
            if need_review or (
                coverage_review
                and draft.semantic_role.value in {"formula", "reference"}
                and draft.confidence < 0.7
            ):
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
        # 全部 unit flush 后才能把 fig:4 / sec:II 等锚点解析成可 join 的 parent_id
        for unit_id, draft in pending:
            unit = await self.session.get(KnowledgeUnit, unit_id)
            parent_anchor = str((getattr(draft, "unit_meta", None) or {}).get("parent_anchor") or "")
            parent_id = anchor_to_id.get(parent_anchor)
            if unit and parent_id and parent_id != unit_id:
                unit.parent_id = parent_id
                kind = str((draft.unit_meta or {}).get("kind") or "")
                extra_type = {
                    "figure": RelationType.HAS_FIGURE.value,
                    "equation": RelationType.HAS_EQUATION.value,
                    "table": RelationType.HAS_TABLE.value,
                }.get(kind)
                self.session.add(
                    KnowledgeRelation(
                        from_id=unit_id,
                        to_id=parent_id,
                        relation_type=RelationType.BELONGS_TO.value,
                        to_kind="unit",
                    )
                )
                if extra_type:
                    self.session.add(
                        KnowledgeRelation(
                            from_id=parent_id,
                            to_id=unit_id,
                            relation_type=extra_type,
                            to_kind="unit",
                        )
                    )
                if self.neo4j_store:
                    self.neo4j_store.upsert_relation(unit_id, parent_id, RelationType.BELONGS_TO.value)
                    if extra_type:
                        self.neo4j_store.upsert_relation(parent_id, unit_id, extra_type)
            for rel in getattr(draft, "relations", None) or []:
                to_key = str(rel.get("to_key") or "")
                to_id = anchor_to_id.get(to_key)
                rel_type = str(rel.get("type") or RelationType.RELATED_TO.value)
                if to_id and to_id != unit_id:
                    self.session.add(
                        KnowledgeRelation(
                            from_id=unit_id,
                            to_id=to_id,
                            relation_type=rel_type,
                            to_kind="unit",
                        )
                    )
                    if self.neo4j_store:
                        self.neo4j_store.upsert_relation(unit_id, to_id, rel_type)
        if coverage_review and unit_ids:
            gap_id = next(
                (
                    uid
                    for uid, draft in pending
                    if (getattr(draft, "unit_meta", None) or {}).get("kind") == "coverage"
                ),
                unit_ids[0],
            )
            self.session.add(
                ReviewTask(ku_id=gap_id, document_id=doc.id, status="pending", comment="ingest coverage incomplete")
            )
        catalog_units = []
        for unit_id in unit_ids:
            unit = await self.session.get(KnowledgeUnit, unit_id)
            if unit:
                catalog_units.append(unit)
        if catalog_units:
            from app.ingestion.catalog_sync import sync_catalog_from_document

            await sync_catalog_from_document(self.session, doc, catalog_units)
        await self.session.commit()
        return {**state, "unit_ids": unit_ids, "status": "extracted", "classification": classification}

    async def index_units(self, state: IngestState) -> IngestState:
        """把已抽取 unit 写入向量 / ES / Neo4j，并重建文档关键字索引；文档状态变为 review。"""
        unit_ids = state.get("unit_ids") or []
        texts: list[str] = []
        units: list[KnowledgeUnit] = []
        for unit_id in unit_ids:
            unit = await self.session.get(KnowledgeUnit, unit_id)
            if not unit:
                continue
            units.append(unit)
            texts.append(unit_embed_text(unit))
        if texts:
            vectors = self.gateway.embed(texts)
            for unit, vector in zip(units, vectors, strict=False):
                self.qdrant.upsert(unit.id, vector, unit_vector_payload(unit))
                if self.es_store:
                    payload = unit_vector_payload(unit)
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
                            "kind": payload.get("kind") or "",
                            "document_id": unit.document_id,
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
        pipeline_step(
            "ingest",
            "index",
            inputs={"document_id": state["document_id"], "unit_count": len(unit_ids)},
            result={
                "indexed": len(units),
                "qdrant": bool(getattr(self.qdrant, "available", True) or getattr(self.qdrant, "_memory", None)),
                "elasticsearch": bool(self.es_store),
                "neo4j": bool(self.neo4j_store),
                "titles": [unit.title[:80] for unit in units[:12]],
                "kinds": _count_kinds(units),
            },
        )
        return {**state, "status": "indexed"}

    async def run_analyze(self, document_id: str, filename: str, raw: bytes) -> IngestState:
        """上传后的分析入口：只 parse+classify，不抽取，等用户确认 Strategy。"""
        pipeline_step(
            "ingest",
            "run_analyze",
            inputs={"document_id": document_id, "filename": filename, "bytes": len(raw)},
            result={"pipeline": "parse→classify→wait"},
        )
        return await self.graph.ainvoke(
            {
                "document_id": document_id,
                "filename": filename,
                "raw": raw,
                "confirmed_strategy": "",
            }
        )

    async def run_extract(self, document_id: str, filename: str, raw: bytes, strategy_type: str) -> IngestState:
        """确认策略后的抽取入口：复用已解析 structure，必要时重新 parse，然后跑完整图含 extract/index。"""
        doc = await self.session.get(Document, document_id)
        structure = (doc.structure if doc else {}) or {}
        text = "\n".join(p.get("text") or "" for p in structure.get("pages") or [])
        if not text or not structure.get("sections"):
            parsed = parse_bytes(filename, raw)
            text = parsed["text"]
            merged = dict(parsed)
            if structure.get("process_config"):
                merged["process_config"] = structure["process_config"]
            structure = merged
        classification = dict((doc.classification if doc else {}) or {})
        classification["knowledge_type"] = strategy_type
        pipeline_step(
            "ingest",
            "run_extract",
            inputs={
                "document_id": document_id,
                "filename": filename,
                "strategy_type": strategy_type,
                "reuse_structure": bool(text and structure.get("sections")),
            },
            result={"pipeline": "parse→classify→extract→index", **structure_digest(structure)},
        )
        return await self.graph.ainvoke(
            {
                "document_id": document_id,
                "filename": filename,
                "raw": raw,
                "text": text,
                "structure": structure,
                "classification": classification,
                "confirmed_strategy": strategy_type,
            }
        )


    async def _purge_document_knowledge(self, document_id: str) -> None:
        """重抽前清掉该文档旧单元、关系、审核任务和向量点，避免图/公式重复入库。"""
        units = (
            await self.session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == document_id))
        ).scalars().all()
        unit_ids = [unit.id for unit in units]
        if not unit_ids:
            return
        tasks = await self.session.execute(select(ReviewTask).where(ReviewTask.ku_id.in_(unit_ids)))
        for task in tasks.scalars().all():
            await self.session.delete(task)
        leftover = await self.session.execute(select(ReviewTask).where(ReviewTask.document_id == document_id))
        for task in leftover.scalars().all():
            await self.session.delete(task)
        rels = await self.session.execute(
            select(KnowledgeRelation).where(
                or_(KnowledgeRelation.from_id.in_(unit_ids), KnowledgeRelation.to_id.in_(unit_ids))
            )
        )
        for rel in rels.scalars().all():
            await self.session.delete(rel)
        for unit in units:
            self.qdrant.delete(unit.id)
            if self.es_store:
                await self.es_store.delete(unit.id)
            await self.session.delete(unit)
        await self.session.flush()


def _sub_domain(structure: dict) -> str:
    """学术论文暂时归到 mixed_signal，便于目录/过滤与芯片数字设计文档分开。"""
    if (structure or {}).get("genre") == "academic_paper":
        return "mixed_signal"
    return ""


def _count_kinds(units: list[KnowledgeUnit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit in units:
        kind = str((unit.unit_meta or {}).get("kind") or "semantic")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def unit_source_level(draft) -> str:
    """draft 未声明来源时默认 AI 生成；低置信公式同样标 AI，避免当官方原文发布。"""
    if draft.source_level:
        return draft.source_level
    if draft.semantic_role.value == "formula" and draft.confidence < 0.7:
        return "AI_GENERATED"
    return "AI_GENERATED"
