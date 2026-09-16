from __future__ import annotations

import re
import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.completeness.checker import CompletenessChecker
from app.domain.enums import QueryIntent, RelationType, SemanticRole, RETRIEVAL_LIFECYCLES
from app.domain.registry import registry
from app.domain.strategy import QueryContext
from app.model_gateway.gateway import ModelGateway
from app.observability.pipeline_log import hit_digest, step as pipeline_step
from app.prompts.loader import load_prompt
from app.retrieval.fusion import rrf_fuse
from app.retrieval.planner import RetrievalPlanner
from app.storage.es_store import ElasticStore
from app.retrieval.doc_index import document_index_blob
from app.retrieval.query_terms import query_terms
from app.storage.models import Document, KnowledgeAcl, KnowledgeBase, KnowledgeRelation, KnowledgeUnit, QueryTrace, User
from app.storage.neo4j_store import Neo4jStore
from app.storage.qdrant_store import QdrantStore
from app.storage.paths import attach_image_refs

TOPIC_PATTERNS = [
    r"\b(CDC|MTBF|FIFO|RTL|FSM|ATPG|MBIST|Setup Time|Hold Time|Metastability|Synchronizer)\b",
    r"(亚稳态|同步器|建立时间|保持时间|跨时钟域|异步FIFO)",
    r"\b(ADC|SAR|FFE|DFE|CTLE|CDR|ENOB|SNDR|BER|TI-ADC)\b",
    r"(Fig\.?\s*\d+[A-Za-z]?|Eq\.?\s*\(?\d+\)?|α-?1|alpha)",
    r"(功耗|均衡|time-interleaved|per-symbol)",
]
FIG_QUERY_RE = re.compile(r"\bFig(?:ure)?\.?\s*(\d+[A-Za-z]?)\b", re.I)
EQ_QUERY_RE = re.compile(r"\bEq(?:uation)?\.?\s*\(?\s*(\d{1,3})", re.I)
EXPAND_RELATIONS = {
    RelationType.HAS_FIGURE.value,
    RelationType.HAS_EQUATION.value,
    RelationType.HAS_TABLE.value,
    RelationType.ILLUSTRATES.value,
    RelationType.EXPLAINED_BY.value,
    RelationType.REFERENCES.value,
    RelationType.BELONGS_TO.value,
}
DEFAULT_UNDERSTAND_PROMPT = """你是芯片设计工程师的检索规划助手。禁止直接回答。输出 JSON：
{"domain":"semiconductor","topics":[],"intent":"definition","risk":"medium"}
"""
DEFAULT_ANSWER_PROMPT = "你是芯片设计工程师助手。只能依据给定 Knowledge Unit 作答，必须引用角色与来源。不得编造文档中不存在的约束或公式。"


class QueryState(TypedDict, total=False):
    query: str
    kb_id: str | None
    user_id: str | None
    understanding: dict[str, Any]
    plan: dict[str, Any]
    hits: list[dict[str, Any]]
    completeness: dict[str, Any]
    answer: str
    citations: list[dict[str, Any]]
    confidence: dict[str, Any]
    retrieval: dict[str, Any]
    trace_id: str


class QueryWorkflow:
    def __init__(
        self,
        session: AsyncSession,
        gateway: ModelGateway,
        qdrant: QdrantStore,
        es_store: ElasticStore | None = None,
        neo4j_store: Neo4jStore | None = None,
    ) -> None:
        self.session = session
        self.emit = None
        self.history = []
        self.gateway = gateway
        self.qdrant = qdrant
        self.es_store = es_store
        self.neo4j_store = neo4j_store
        self.checker = CompletenessChecker(gateway)
        self.planner = RetrievalPlanner(session)
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(QueryState)
        graph.add_node("understand", self.understand)
        graph.add_node("plan", self.plan)
        graph.add_node("retrieve", self.retrieve)
        graph.add_node("complete", self.complete)
        graph.add_node("answer", self.answer)
        graph.add_edge(START, "understand")
        graph.add_edge("understand", "plan")
        graph.add_edge("plan", "retrieve")
        graph.add_edge("retrieve", "complete")
        graph.add_edge("complete", "answer")
        graph.add_edge("answer", END)
        return graph.compile()

    async def understand(self, state: QueryState) -> QueryState:
        query = state["query"]
        parsed = await asyncio.to_thread(self.gateway.chat_json,
            load_prompt("query-understanding", DEFAULT_UNDERSTAND_PROMPT),
            f"历史对话（用于理解当前追问）：{self.history}\n当前问题：{query}" if self.history else query,
        )
        intent = _parse_intent(query, parsed.get("intent"))
        topics = parsed.get("topics") or _extract_topics(query)
        understanding = {
            "domain": parsed.get("domain") or "semiconductor",
            "topics": topics,
            "intent": intent.value,
            "risk": parsed.get("risk") or ("high" if intent in {QueryIntent.SOLUTION, QueryIntent.RISK} else "medium"),
        }
        pipeline_step(
            "retrieve",
            "understand",
            inputs={"query": query, "kb_id": state.get("kb_id"), "llm_intent": parsed.get("intent"), "llm_topics": parsed.get("topics")},
            result=understanding,
        )
        return {**state, "understanding": understanding}

    async def plan(self, state: QueryState) -> QueryState:
        understanding = state["understanding"]
        intent = QueryIntent(understanding["intent"])
        kb = None
        if state.get("kb_id"):
            kb = await self.session.get(KnowledgeBase, state["kb_id"])
        knowledge_type = "technical_concept"
        if kb and kb.strategy:
            knowledge_type = kb.strategy.knowledge_type
        strategy = registry.get(knowledge_type)
        ctx = QueryContext(
            query=state["query"],
            kb_id=state.get("kb_id"),
            domain=understanding["domain"],
            intent=intent,
            topics=understanding["topics"],
        )
        plan = strategy.plan(ctx)
        configured = await self.planner.load_steps(intent.value)
        plan_payload = {
            "intent": plan.intent.value,
            "topics": plan.topics,
            "required_roles": [r.value for r in plan.required_roles],
            "graph_expand": plan.graph_expand,
            "search_strategy": plan.search_strategy,
            "completeness_check": plan.completeness_check,
            "steps": configured or plan.steps,
            "knowledge_type": knowledge_type,
            "expand_kinds": ["figure", "equation", "table"],
        }
        pipeline_step(
            "retrieve",
            "plan",
            inputs={
                "query": state["query"],
                "kb_id": state.get("kb_id"),
                "intent": intent.value,
                "strategy": strategy.__class__.__name__,
            },
            result={
                **plan_payload,
                "role_filter": "boost_not_must",
                "channels": ["anchor_exact", "vector", "keyword_es_or_sql", "document_index", "graph_if_needed"],
            },
        )
        return {**state, "plan": plan_payload}

    async def retrieve(self, state: QueryState) -> QueryState:
        plan = state["plan"]
        roles = plan["required_roles"]
        kb_id = state.get("kb_id")
        allowed_kbs = await self._allowed_kb_ids(state.get("user_id"), kb_id)
        query_vec = (await asyncio.to_thread(self.gateway.embed, [state["query"]]))[0]
        target_kb = kb_id if kb_id else (allowed_kbs[0] if len(allowed_kbs) == 1 else None)
        extra_filters = {"kb_id": allowed_kbs} if not target_kb and allowed_kbs else None
        anchors = query_anchor_keys(state["query"])
        exact_hits = await self._anchor_exact_hits(state["query"], target_kb, allowed_kbs)
        vector_hits = await asyncio.to_thread(self.qdrant.search,
            query_vec,
            limit=50,
            kb_id=target_kb,
            roles=roles,
            extra_filters=extra_filters,
        )
        keyword_hits: list[dict[str, Any]] = []
        if self.es_store:
            keyword_hits = await self.es_store.search(
                state["query"], limit=50, kb_id=target_kb, roles=roles
            )
        if not keyword_hits:
            keyword_hits = await self._sql_keyword_search(state["query"], target_kb, None, allowed_kbs)
        index_hits = await self._document_index_hits(state["query"], target_kb, None, allowed_kbs)
        if index_hits:
            seen = {hit.get("id") for hit in keyword_hits}
            keyword_hits.extend(hit for hit in index_hits if hit.get("id") not in seen)

        graph_hits: list[dict[str, Any]] = []
        if plan.get("graph_expand") and self.neo4j_store:
            for topic in plan.get("topics") or []:
                graph_hits.extend(
                    {"id": n["id"], "score": 0.5, "payload": n}
                    for n in self.neo4j_store.expand(topic)
                    if n.get("id")
                )

        fused = rrf_fuse(
            [
                [{"id": h["id"], **h} for h in exact_hits],
                [{"id": h["id"], **h} for h in vector_hits],
                [{"id": h["id"], **h} for h in keyword_hits],
                graph_hits,
            ],
            weights=[1.4, 1.0, 1.0, 0.6],
            limit=50,
        )
        for item in fused:
            role = (item.get("payload") or {}).get("semantic_role")
            if role in set(roles or []):
                item["fused_score"] = float(item.get("fused_score") or 0) * 1.2
        fused.sort(key=lambda item: item.get("fused_score") or 0, reverse=True)

        documents = []
        unit_map: dict[str, KnowledgeUnit] = {}
        for item in fused:
            unit = await self.session.get(KnowledgeUnit, item["id"])
            if not unit or not _published(unit):
                continue
            if allowed_kbs and unit.kb_id not in allowed_kbs:
                continue
            unit_map[unit.id] = unit
            documents.append(f"{unit.title}\n{unit.content}")
        order = await asyncio.to_thread(self.gateway.rerank,state["query"], documents, top_n=12)
        reranked = []
        unit_list = list(unit_map.values())
        for idx, score in order:
            if idx >= len(unit_list):
                continue
            reranked.append(_hit_from_unit(unit_list[idx], score, via="rerank"))
        if not reranked:
            reranked = [_hit_from_unit(unit, 0.5, via="fused") for unit in unit_list[:12]]

        expanded = await self._expand_neighbors(reranked, allowed_kbs, plan.get("expand_kinds") or [])
        retrieval = {
            "keyword": len(keyword_hits),
            "vector": len(vector_hits),
            "graph": len(graph_hits),
            "exact": len(exact_hits),
            "fused": len(fused),
            "reranked": len(reranked),
            "expanded": len(expanded),
        }
        pipeline_step(
            "retrieve",
            "retrieve",
            inputs={
                "query": state["query"],
                "kb_id": target_kb,
                "allowed_kbs": allowed_kbs,
                "roles_boost": roles,
                "anchors": anchors,
                "qdrant_available": bool(getattr(self.qdrant, "available", False)),
                "es_available": bool(getattr(self.es_store, "available", False)) if self.es_store else False,
            },
            result={
                "channels": retrieval,
                "exact": hit_digest(exact_hits),
                "vector": hit_digest(vector_hits),
                "keyword": hit_digest(keyword_hits),
                "graph": hit_digest(graph_hits),
                "after_rerank_expand": hit_digest(expanded),
            },
        )
        return {
            **state,
            "hits": expanded,
            "retrieval": retrieval,
        }

    async def complete(self, state: QueryState) -> QueryState:
        plan = state["plan"]
        hits = state.get("hits") or []
        ctx = QueryContext(
            query=state["query"],
            kb_id=state.get("kb_id"),
            intent=QueryIntent(plan["intent"]),
            topics=plan.get("topics") or [],
        )
        result = await asyncio.to_thread(self.checker.check,
            ctx,
            plan.get("required_roles") or [],
            [h["title"] for h in hits],
            [h["semantic_role"] for h in hits],
        )
        if result.need_secondary_retrieval and result.missing:
            secondary_query = result.secondary_query or state["query"]
            missing_before = list(result.missing)
            extra_vec = (await asyncio.to_thread(self.gateway.embed, [secondary_query]))[0]
            extra = await asyncio.to_thread(self.qdrant.search,extra_vec, limit=10, kb_id=state.get("kb_id"), roles=result.missing)
            existing = {h["id"] for h in hits}
            allowed_kbs = await self._allowed_kb_ids(state.get("user_id"), state.get("kb_id"))
            for item in extra:
                if item["id"] in existing:
                    continue
                unit = await self.session.get(KnowledgeUnit, item["id"])
                if not unit or not _published(unit):
                    continue
                hits.append(_hit_from_unit(unit, item["score"], via="secondary"))
            hits = await self._expand_neighbors(hits, allowed_kbs, plan.get("expand_kinds") or [])
            result = await asyncio.to_thread(self.checker.check,
                ctx,
                plan.get("required_roles") or [],
                [h["title"] for h in hits],
                [h["semantic_role"] for h in hits],
            )
            pipeline_step(
                "retrieve",
                "complete_secondary",
                inputs={"secondary_query": secondary_query, "missing_before": missing_before},
                result={"hit_count": len(hits), "score": result.completeness_score, "hits": hit_digest(hits)},
            )
        completeness = {
            "required_knowledge": result.required_knowledge,
            "covered": result.covered,
            "missing": result.missing,
            "completeness_score": result.completeness_score,
            "need_secondary_retrieval": result.need_secondary_retrieval,
            "secondary_query": result.secondary_query,
        }
        pipeline_step(
            "retrieve",
            "complete",
            inputs={"query": state["query"], "required_roles": plan.get("required_roles"), "hit_count": len(hits)},
            result=completeness,
        )
        return {
            **state,
            "hits": hits,
            "completeness": completeness,
        }

    async def answer(self, state: QueryState) -> QueryState:
        hits = _order_context_hits(state.get("hits") or [])
        completeness = state.get("completeness") or {}
        doc_cache: dict[str, Document] = {}
        context_blocks = []
        citations = []
        for hit in hits[:12]:
            kind = hit.get("kind") or ""
            label = f"[{hit['semantic_role']}" + (f"/{kind}" if kind else "") + "]"
            extra = ""
            if hit.get("image_url") or hit.get("image_key"):
                extra = f"\n相关图: {hit.get('title')} image_url={hit.get('image_url') or ''} image_key={hit.get('image_key') or ''}"
            context_blocks.append(
                f"{label} {hit['title']}\n{hit['content']}{extra}\n来源: {hit.get('source_chapter')} {hit.get('source_section')} p.{hit.get('source_page')}"
            )
            doc_title, doi = "", ""
            doc_id = hit.get("document_id")
            if doc_id:
                if doc_id not in doc_cache:
                    doc_cache[doc_id] = await self.session.get(Document, doc_id)
                doc = doc_cache.get(doc_id)
                if doc:
                    meta = (doc.index_meta or {}) if hasattr(doc, "index_meta") else {}
                    structure_meta = ((doc.structure or {}).get("metadata") if doc.structure else {}) or {}
                    doi = str(meta.get("doi") or structure_meta.get("doi") or "")
                    doc_title = str(meta.get("title") or structure_meta.get("title") or doc.filename)
            citations.append(
                {
                    "knowledge_id": hit["id"],
                    "title": hit["title"],
                    "role": hit["semantic_role"],
                    "kind": kind,
                    "chapter": hit.get("source_chapter"),
                    "page": hit.get("source_page"),
                    "section": hit.get("source_section"),
                    "anchor": hit.get("anchor") or "",
                    "image_key": hit.get("image_key") or "",
                    "image_url": hit.get("image_url") or "",
                    "doi": doi,
                    "document_id": doc_id,
                    "document_title": doc_title,
                    "via": hit.get("via") or "",
                }
            )
        prompt = f"历史对话（仅用于理解追问，不作为知识依据）：{self.history}\n问题：{state['query']}\n完整性：{completeness}\n知识：\n" + "\n\n".join(context_blocks)
        if self.emit:
            await self.emit("citations", {"citations": citations})
            generated = ""
            async for delta in self.gateway.chat_text_stream(_answer_system(), prompt):
                generated += delta
                await self.emit("delta", {"text": delta})
        else:
            generated = await asyncio.to_thread(self.gateway.chat_text, _answer_system(), prompt)
        answer_source = "llm" if generated else "heuristic"
        if not generated:
            generated = _heuristic_answer(state["query"], hits, completeness)
            if self.emit:
                await self.emit("delta", {"text": generated})
        confidence = _confidence(hits, completeness)
        trace = QueryTrace(
            kb_id=state.get("kb_id"),
            user_id=state.get("user_id"),
            query=state["query"],
            understanding=state.get("understanding") or {},
            plan=state.get("plan") or {},
            retrieval=state.get("retrieval") or {},
            completeness=completeness,
            answer=generated,
            citations=citations,
            confidence=confidence,
        )
        self.session.add(trace)
        if self.emit:
            await self.session.flush()
        else:
            await self.session.commit()
        pipeline_step(
            "retrieve",
            "answer",
            inputs={"query": state["query"], "context_hits": len(hits[:12])},
            result={
                "trace_id": trace.id,
                "answer_source": answer_source,
                "answer_preview": generated[:240],
                "confidence": confidence,
                "citations": [
                    {
                        "title": item.get("title"),
                        "kind": item.get("kind"),
                        "role": item.get("role"),
                        "anchor": item.get("anchor"),
                        "via": item.get("via"),
                        "image_key": item.get("image_key"),
                        "image_url": item.get("image_url"),
                    }
                    for item in citations[:12]
                ],
            },
        )
        return {
            **state,
            "answer": generated,
            "citations": citations,
            "confidence": confidence,
            "trace_id": trace.id,
        }

    async def run(self, query: str, kb_id: str | None, user_id: str | None = None) -> QueryState:
        pipeline_step(
            "retrieve",
            "run",
            inputs={"query": query, "kb_id": kb_id, "user_id": user_id},
            result={"pipeline": "understand→plan→retrieve→complete→answer"},
        )
        state = {"query": query, "kb_id": kb_id, "user_id": user_id}
        if not self.emit:
            return await self.graph.ainvoke(state)
        for name in ("understand", "plan", "retrieve", "complete", "answer"):
            await self.emit("status", {"stage": name})
            state = await getattr(self, name)(state)
            await self.emit("metadata", {k: v for k, v in state.items() if k not in {"answer", "query", "user_id", "kb_id"}})
        return state

    async def _allowed_kb_ids(self, user_id: str | None, kb_id: str | None) -> list[str]:
        if kb_id:
            return [kb_id]
        if not user_id:
            result = await self.session.execute(select(KnowledgeBase.id))
            return [row[0] for row in result.all()]
        user = await self.session.get(User, user_id)
        result = await self.session.execute(select(KnowledgeBase))
        bases = result.scalars().all()
        allowed: list[str] = []
        for kb in bases:
            if kb.access_scope == "public":
                allowed.append(kb.id)
                continue
            acl = await self.session.execute(
                select(KnowledgeAcl).where(KnowledgeAcl.kb_id == kb.id)
            )
            rules = acl.scalars().all()
            if not rules:
                allowed.append(kb.id)
                continue
            for rule in rules:
                if user and rule.principal_type == "role" and rule.principal_id == user.role:
                    allowed.append(kb.id)
                if user and rule.principal_type == "user" and rule.principal_id == user.id:
                    allowed.append(kb.id)
        return allowed

    async def _sql_keyword_search(
        self, query: str, kb_id: str | None, roles: list[str], allowed_kbs: list[str]
    ) -> list[dict[str, Any]]:
        stmt = select(KnowledgeUnit).where(
            KnowledgeUnit.lifecycle.in_(list(RETRIEVAL_LIFECYCLES))
        )
        if kb_id:
            stmt = stmt.where(KnowledgeUnit.kb_id == kb_id)
        elif allowed_kbs:
            stmt = stmt.where(KnowledgeUnit.kb_id.in_(allowed_kbs))
        tokens = query_terms(query)
        if tokens:
            stmt = stmt.where(
                or_(
                    *[
                        KnowledgeUnit.title.ilike(f"%{tok}%") | KnowledgeUnit.content.ilike(f"%{tok}%")
                        for tok in tokens[:8]
                    ]
                )
            )
        result = await self.session.execute(stmt.limit(50))
        hits = []
        for unit in result.scalars().all():
            hits.append(self._unit_hit(unit, 1.0))
        return hits

    def _unit_hit(self, unit: KnowledgeUnit, score: float) -> dict[str, Any]:
        meta = unit.unit_meta or {}
        return {
            "id": unit.id,
            "score": score,
            "payload": {
                "title": unit.title,
                "semantic_role": unit.semantic_role,
                "kind": meta.get("kind") or "",
                "anchor": meta.get("anchor") or "",
            },
            "source": {"title": unit.title, "content": unit.content},
        }

    async def _document_index_hits(
        self, query: str, kb_id: str | None, roles: list[str], allowed_kbs: list[str]
    ) -> list[dict[str, Any]]:
        tokens = [tok.lower() for tok in query_terms(query)]
        if not tokens:
            return []
        doc_ids: list[str] = []
        if self.es_store:
            doc_ids = await self.es_store.search_document_ids(query, kb_id)
        stmt = select(Document)
        if kb_id:
            stmt = stmt.where(Document.kb_id == kb_id)
        elif allowed_kbs:
            stmt = stmt.where(Document.kb_id.in_(allowed_kbs))
        for doc in (await self.session.execute(stmt)).scalars().all():
            blob = document_index_blob(doc)
            if any(tok in blob for tok in tokens[:8]):
                doc_ids.append(doc.id)
        doc_ids = list(dict.fromkeys(doc_ids))
        if not doc_ids:
            return []
        unit_stmt = select(KnowledgeUnit).where(
            KnowledgeUnit.document_id.in_(doc_ids),
            KnowledgeUnit.lifecycle.in_(list(RETRIEVAL_LIFECYCLES)),
        )
        if kb_id:
            unit_stmt = unit_stmt.where(KnowledgeUnit.kb_id == kb_id)
        elif allowed_kbs:
            unit_stmt = unit_stmt.where(KnowledgeUnit.kb_id.in_(allowed_kbs))
        units = (await self.session.execute(unit_stmt.limit(50))).scalars().all()
        return [self._unit_hit(unit, 1.2) for unit in units]

    async def _anchor_exact_hits(
        self, query: str, kb_id: str | None, allowed_kbs: list[str]
    ) -> list[dict[str, Any]]:
        keys = query_anchor_keys(query)
        if not keys:
            return []
        stmt = select(KnowledgeUnit).where(
            KnowledgeUnit.lifecycle.in_(list(RETRIEVAL_LIFECYCLES)),
            or_(
                KnowledgeUnit.source_section.in_(keys),
                *[KnowledgeUnit.title.ilike(f"%{key.split(':', 1)[-1]}%") for key in keys[:4]],
            ),
        )
        if kb_id:
            stmt = stmt.where(KnowledgeUnit.kb_id == kb_id)
        elif allowed_kbs:
            stmt = stmt.where(KnowledgeUnit.kb_id.in_(allowed_kbs))
        units = (await self.session.execute(stmt.limit(20))).scalars().all()
        matched = []
        for unit in units:
            meta = unit.unit_meta or {}
            anchor = str(meta.get("anchor") or unit.source_section or "")
            if anchor in keys or unit.source_section in keys:
                matched.append(self._unit_hit(unit, 1.6))
        return matched

    async def _expand_neighbors(
        self,
        hits: list[dict[str, Any]],
        allowed_kbs: list[str],
        expand_kinds: list[str],
    ) -> list[dict[str, Any]]:
        if not hits:
            return hits
        existing = {hit["id"] for hit in hits}
        extra: list[dict[str, Any]] = []
        parent_hits: list[dict[str, Any]] = []
        kind_counts: dict[str, int] = {}
        ids = list(existing)
        result = await self.session.execute(
            select(KnowledgeRelation).where(
                or_(KnowledgeRelation.from_id.in_(ids), KnowledgeRelation.to_id.in_(ids)),
                KnowledgeRelation.relation_type.in_(list(EXPAND_RELATIONS)),
            )
        )
        neighbor_ids: list[str] = []
        for rel in result.scalars().all():
            if rel.from_id not in existing:
                neighbor_ids.append(rel.from_id)
            if rel.to_id not in existing:
                neighbor_ids.append(rel.to_id)
        for hit in hits:
            unit = await self.session.get(KnowledgeUnit, hit["id"])
            if unit and unit.parent_id and unit.parent_id not in existing:
                neighbor_ids.append(unit.parent_id)
        for neighbor_id in dict.fromkeys(neighbor_ids):
            unit = await self.session.get(KnowledgeUnit, neighbor_id)
            if not unit or not _published(unit):
                continue
            if allowed_kbs and unit.kb_id not in allowed_kbs:
                continue
            kind = str((unit.unit_meta or {}).get("kind") or "")
            via = "parent" if any(h.get("parent_id") == unit.id for h in hits) or kind == "section" else "relation"
            if via == "parent":
                parent_hits.append(_hit_from_unit(unit, 0.45, via="parent"))
                existing.add(unit.id)
                continue
            if expand_kinds and kind and kind not in expand_kinds and kind not in {"citation", "section"}:
                if kind not in {"figure", "equation", "table", "citation"}:
                    continue
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            if kind in {"figure", "equation", "table", "citation"} and kind_counts[kind] > 3:
                continue
            extra.append(_hit_from_unit(unit, 0.4, via="relation"))
            existing.add(unit.id)
        return parent_hits + hits + extra


def query_anchor_keys(query: str) -> list[str]:
    keys: list[str] = []
    for match in FIG_QUERY_RE.finditer(query):
        keys.append(f"fig:{match.group(1)}")
    for match in EQ_QUERY_RE.finditer(query):
        keys.append(f"eq:{match.group(1)}")
    return list(dict.fromkeys(keys))


def _hit_from_unit(unit: KnowledgeUnit, score: float, via: str = "") -> dict[str, Any]:
    meta = attach_image_refs(unit.document_id, unit.unit_meta)
    return {
        "id": unit.id,
        "title": unit.title,
        "content": unit.content,
        "semantic_role": unit.semantic_role,
        "source_chapter": unit.source_chapter,
        "source_page": unit.source_page,
        "source_section": unit.source_section,
        "document_id": unit.document_id,
        "parent_id": unit.parent_id,
        "score": score,
        "source_level": unit.source_level,
        "confidence": unit.confidence,
        "kind": meta.get("kind") or "",
        "anchor": meta.get("anchor") or "",
        "image_key": meta.get("image_key") or "",
        "image_url": meta.get("image_url") or "",
        "via": via,
    }


def _published(unit: KnowledgeUnit) -> bool:
    """问答只读检索就绪状态：已发布、已批准，以及抽取完成待审核的 AI_PROCESSED。"""
    return unit.lifecycle in RETRIEVAL_LIFECYCLES


def _order_context_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents = [hit for hit in hits if hit.get("via") == "parent"]
    related = [hit for hit in hits if hit.get("via") == "relation"]
    core = [hit for hit in hits if hit.get("via") not in {"parent", "relation"}]
    return parents + core + related


def _answer_system() -> str:
    return load_prompt("answer-generator", DEFAULT_ANSWER_PROMPT)


def _parse_intent(query: str, raw: str | None) -> QueryIntent:
    mapping = {
        "definition": QueryIntent.DEFINITION,
        "cause_analysis": QueryIntent.CAUSE,
        "cause": QueryIntent.CAUSE,
        "solution": QueryIntent.SOLUTION,
        "risk_analysis": QueryIntent.RISK,
        "risk": QueryIntent.RISK,
        "comparison": QueryIntent.COMPARISON,
        "compare": QueryIntent.COMPARISON,
    }
    if raw in mapping:
        return mapping[raw]
    lowered = query.lower()
    if any(k in query for k in ["对比", "比较", "vs", "先前"]) or "compar" in lowered:
        return QueryIntent.COMPARISON
    if any(k in query for k in ["什么时候", "何时", "什么情况下"]):
        return QueryIntent.SOLUTION
    if any(k in query for k in ["如何", "怎么", "解决", "设计"]):
        return QueryIntent.SOLUTION
    if any(k in query for k in ["为什么", "原因", "导致"]):
        return QueryIntent.CAUSE
    if any(k in query for k in ["风险", "失败", "例外"]):
        return QueryIntent.RISK
    if any(k in query for k in ["什么是", "定义", "是什么"]):
        return QueryIntent.DEFINITION
    return QueryIntent.DEFINITION


def _extract_topics(query: str) -> list[str]:
    found: list[str] = []
    for pattern in TOPIC_PATTERNS:
        for item in re.findall(pattern, query, flags=re.IGNORECASE):
            if isinstance(item, tuple):
                found.extend(part for part in item if part)
            elif item:
                found.append(item)
    return found or [query[:24]]


def _heuristic_answer(query: str, hits: list[dict[str, Any]], completeness: dict[str, Any]) -> str:
    if not hits:
        return "当前检索未命中可回答该问题的知识单元。请确认文档已抽取完成；高风险公式/规则仍需在「知识审核」发布后才会进入问答。"
    grouped: dict[str, list[str]] = {}
    for hit in hits:
        grouped.setdefault(hit["semantic_role"], []).append(hit["content"][:400])
    parts = [f"针对问题：{query}\n"]
    order = [
        SemanticRole.DEFINITION.value,
        SemanticRole.ROOT_CAUSE.value,
        SemanticRole.PRINCIPLE.value,
        SemanticRole.SOLUTION.value,
        SemanticRole.CONSTRAINT.value,
        SemanticRole.EXAMPLE.value,
        SemanticRole.EXCEPTION.value,
        SemanticRole.FORMULA.value,
        SemanticRole.METRIC.value,
        SemanticRole.INTERFACE.value,
        SemanticRole.REFERENCE.value,
    ]
    titles = {
        SemanticRole.DEFINITION.value: "定义",
        SemanticRole.ROOT_CAUSE.value: "问题原因",
        SemanticRole.PRINCIPLE.value: "原理",
        SemanticRole.SOLUTION.value: "解决方案",
        SemanticRole.CONSTRAINT.value: "设计约束",
        SemanticRole.EXAMPLE.value: "示例",
        SemanticRole.EXCEPTION.value: "例外",
        SemanticRole.FORMULA.value: "公式",
        SemanticRole.METRIC.value: "指标",
        SemanticRole.INTERFACE.value: "结构",
        SemanticRole.REFERENCE.value: "参考文献",
    }
    for role in order:
        if role in grouped:
            parts.append(f"## {titles[role]}\n{grouped[role][0]}")
    figures = [hit for hit in hits if hit.get("kind") == "figure"]
    for fig in figures[:2]:
        parts.append(f"相关图：{fig.get('title')} — {fig.get('content', '')[:180]} 地址：{fig.get('image_url') or fig.get('image_key') or ''}")
    missing = completeness.get("missing") or []
    if missing:
        parts.append("\n当前覆盖不完整，缺失：" + ", ".join(missing))
    parts.append("\n知识来源：\n" + "\n".join(f"- {h['title']} ({h.get('source_chapter') or 'N/A'}) p.{h.get('source_page')}" for h in hits[:5]))
    return "\n\n".join(parts)


def _confidence(hits: list[dict[str, Any]], completeness: dict[str, Any]) -> dict[str, Any]:
    authority = 1.0 if any(h.get("source_level") in {"OFFICIAL", "REVIEWED"} for h in hits) else 0.7
    relevance = min(1.0, (hits[0]["score"] if hits else 0) + 0.5)
    complete = float(completeness.get("completeness_score") or 0)
    consistency = 0.8 if len({h.get("semantic_role") for h in hits}) >= 2 else 0.6
    ai = 0.6
    final = authority * 0.30 + relevance * 0.25 + complete * 0.20 + consistency * 0.15 + ai * 0.10
    return {
        "source_authority": round(authority, 2),
        "retrieval_relevance": round(relevance, 2),
        "completeness": round(complete, 2),
        "consistency": round(consistency, 2),
        "ai_confidence": ai,
        "final": round(final, 2),
        "level": "high" if final >= 0.85 else "medium" if final >= 0.7 else "low",
    }
