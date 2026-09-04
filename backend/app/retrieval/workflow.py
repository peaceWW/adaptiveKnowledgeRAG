from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.completeness.checker import CompletenessChecker
from app.domain.enums import INTENT_ROLE_MAP, KnowledgeLifecycle, QueryIntent, SemanticRole
from app.domain.registry import registry
from app.domain.strategy import QueryContext
from app.model_gateway.gateway import ModelGateway
from app.retrieval.fusion import rrf_fuse
from app.retrieval.planner import RetrievalPlanner
from app.storage.es_store import ElasticStore
from app.retrieval.doc_index import document_index_blob
from app.storage.models import Document, KnowledgeAcl, KnowledgeBase, KnowledgeUnit, QueryTrace, User
from app.storage.neo4j_store import Neo4jStore
from app.storage.qdrant_store import QdrantStore

TOPIC_PATTERNS = [
    r"\b(CDC|MTBF|FIFO|RTL|FSM|ATPG|MBIST|Setup Time|Hold Time|Metastability|Synchronizer)\b",
    r"(亚稳态|同步器|建立时间|保持时间|跨时钟域|异步FIFO)",
]


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
        parsed = self.gateway.chat_json(
            """你是知识检索规划器的查询理解模块。禁止直接回答用户问题。
输出 JSON：
{"domain":"semiconductor","topics":[],"intent":"definition|cause_analysis|solution|risk_analysis","risk":"low|high"}
intent 只能是上述枚举。""",
            query,
        )
        intent = _parse_intent(query, parsed.get("intent"))
        topics = parsed.get("topics") or _extract_topics(query)
        understanding = {
            "domain": parsed.get("domain") or "semiconductor",
            "topics": topics,
            "intent": intent.value,
            "risk": parsed.get("risk") or ("high" if intent in {QueryIntent.SOLUTION, QueryIntent.RISK} else "medium"),
        }
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
        return {
            **state,
            "plan": {
                "intent": plan.intent.value,
                "topics": plan.topics,
                "required_roles": [r.value for r in plan.required_roles],
                "graph_expand": plan.graph_expand,
                "search_strategy": plan.search_strategy,
                "completeness_check": plan.completeness_check,
                "steps": configured or plan.steps,
                "knowledge_type": knowledge_type,
            },
        }

    async def retrieve(self, state: QueryState) -> QueryState:
        plan = state["plan"]
        roles = plan["required_roles"]
        kb_id = state.get("kb_id")
        allowed_kbs = await self._allowed_kb_ids(state.get("user_id"), kb_id)
        query_vec = self.gateway.embed([state["query"]])[0]
        extra = {"kb_id": allowed_kbs} if len(allowed_kbs) > 1 else None
        target_kb = kb_id if kb_id else (allowed_kbs[0] if len(allowed_kbs) == 1 else None)
        vector_hits = self.qdrant.search(
            query_vec,
            limit=50,
            kb_id=target_kb,
            roles=roles,
            extra_filters={"kb_id": allowed_kbs} if not target_kb and allowed_kbs else None,
        )
        keyword_hits: list[dict[str, Any]] = []
        if self.es_store:
            keyword_hits = await self.es_store.search(
                state["query"], limit=50, kb_id=target_kb, roles=roles
            )
        if not keyword_hits:
            keyword_hits = await self._sql_keyword_search(state["query"], target_kb, roles, allowed_kbs)
        index_hits = await self._document_index_hits(state["query"], target_kb, roles, allowed_kbs)
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
                [{"id": h["id"], **h} for h in vector_hits],
                [{"id": h["id"], **h} for h in keyword_hits],
                graph_hits,
            ],
            weights=[1.0, 1.0, 0.6],
            limit=50,
        )
        documents = []
        unit_map: dict[str, KnowledgeUnit] = {}
        for item in fused:
            unit = await self.session.get(KnowledgeUnit, item["id"])
            if not unit or unit.lifecycle not in {
                KnowledgeLifecycle.PUBLISHED.value,
                KnowledgeLifecycle.APPROVED.value,
            }:
                continue
            if allowed_kbs and unit.kb_id not in allowed_kbs:
                continue
            unit_map[unit.id] = unit
            documents.append(f"{unit.title}\n{unit.content}")
        order = self.gateway.rerank(state["query"], documents, top_n=12)
        reranked = []
        unit_list = list(unit_map.values())
        for idx, score in order:
            if idx >= len(unit_list):
                continue
            unit = unit_list[idx]
            reranked.append(
                {
                    "id": unit.id,
                    "title": unit.title,
                    "content": unit.content,
                    "semantic_role": unit.semantic_role,
                    "source_chapter": unit.source_chapter,
                    "source_page": unit.source_page,
                    "source_section": unit.source_section,
                    "document_id": unit.document_id,
                    "score": score,
                    "source_level": unit.source_level,
                    "confidence": unit.confidence,
                }
            )
        if not reranked:
            reranked = [
                {
                    "id": unit.id,
                    "title": unit.title,
                    "content": unit.content,
                    "semantic_role": unit.semantic_role,
                    "source_chapter": unit.source_chapter,
                    "source_page": unit.source_page,
                    "source_section": unit.source_section,
                    "document_id": unit.document_id,
                    "score": 0.5,
                    "source_level": unit.source_level,
                    "confidence": unit.confidence,
                }
                for unit in unit_list[:12]
            ]
        return {
            **state,
            "hits": reranked,
            "retrieval": {
                "keyword": len(keyword_hits),
                "vector": len(vector_hits),
                "graph": len(graph_hits),
                "fused": len(fused),
                "reranked": len(reranked),
            },
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
        result = self.checker.check(
            ctx,
            plan.get("required_roles") or [],
            [h["title"] for h in hits],
            [h["semantic_role"] for h in hits],
        )
        if result.need_secondary_retrieval and result.missing:
            extra_vec = self.gateway.embed([result.secondary_query or state["query"]])[0]
            extra = self.qdrant.search(extra_vec, limit=10, kb_id=state.get("kb_id"), roles=result.missing)
            existing = {h["id"] for h in hits}
            for item in extra:
                if item["id"] in existing:
                    continue
                unit = await self.session.get(KnowledgeUnit, item["id"])
                if not unit:
                    continue
                if unit.lifecycle not in {
                    KnowledgeLifecycle.PUBLISHED.value,
                    KnowledgeLifecycle.APPROVED.value,
                }:
                    continue
                hits.append(
                    {
                        "id": unit.id,
                        "title": unit.title,
                        "content": unit.content,
                        "semantic_role": unit.semantic_role,
                        "source_chapter": unit.source_chapter,
                        "source_page": unit.source_page,
                        "source_section": unit.source_section,
                        "document_id": unit.document_id,
                        "score": item["score"],
                        "source_level": unit.source_level,
                        "confidence": unit.confidence,
                    }
                )
            result = self.checker.check(
                ctx,
                plan.get("required_roles") or [],
                [h["title"] for h in hits],
                [h["semantic_role"] for h in hits],
            )
        return {
            **state,
            "hits": hits,
            "completeness": {
                "required_knowledge": result.required_knowledge,
                "covered": result.covered,
                "missing": result.missing,
                "completeness_score": result.completeness_score,
                "need_secondary_retrieval": result.need_secondary_retrieval,
                "secondary_query": result.secondary_query,
            },
        }

    async def answer(self, state: QueryState) -> QueryState:
        hits = state.get("hits") or []
        completeness = state.get("completeness") or {}
        context_blocks = []
        citations = []
        for hit in hits[:8]:
            context_blocks.append(
                f"[{hit['semantic_role']}] {hit['title']}\n{hit['content']}\n来源: {hit.get('source_chapter')} p.{hit.get('source_page')}"
            )
            citations.append(
                {
                    "knowledge_id": hit["id"],
                    "title": hit["title"],
                    "role": hit["semantic_role"],
                    "chapter": hit.get("source_chapter"),
                    "page": hit.get("source_page"),
                    "section": hit.get("source_section"),
                }
            )
        generated = self.gateway.chat_text(
            "你是企业知识助手。只能依据给定 Knowledge Unit 作答，必须引用角色与来源。不得编造文档中不存在的约束或公式。",
            f"问题：{state['query']}\n完整性：{completeness}\n知识：\n" + "\n\n".join(context_blocks),
        )
        if not generated:
            generated = _heuristic_answer(state["query"], hits, completeness)
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
        await self.session.commit()
        return {
            **state,
            "answer": generated,
            "citations": citations,
            "confidence": confidence,
            "trace_id": trace.id,
        }

    async def run(self, query: str, kb_id: str | None, user_id: str | None = None) -> QueryState:
        return await self.graph.ainvoke({"query": query, "kb_id": kb_id, "user_id": user_id})

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
            KnowledgeUnit.lifecycle.in_(
                [KnowledgeLifecycle.PUBLISHED.value, KnowledgeLifecycle.APPROVED.value]
            )
        )
        if kb_id:
            stmt = stmt.where(KnowledgeUnit.kb_id == kb_id)
        elif allowed_kbs:
            stmt = stmt.where(KnowledgeUnit.kb_id.in_(allowed_kbs))
        if roles:
            stmt = stmt.where(KnowledgeUnit.semantic_role.in_(roles))
        tokens = [t for t in re.split(r"\s+", query) if len(t) >= 2]
        if tokens:
            stmt = stmt.where(
                or_(
                    *[
                        KnowledgeUnit.title.ilike(f"%{tok}%") | KnowledgeUnit.content.ilike(f"%{tok}%")
                        for tok in tokens[:6]
                    ]
                )
            )
        result = await self.session.execute(stmt.limit(50))
        hits = []
        for unit in result.scalars().all():
            hits.append(self._unit_hit(unit, 1.0))
        return hits

    def _unit_hit(self, unit: KnowledgeUnit, score: float) -> dict[str, Any]:
        return {
            "id": unit.id,
            "score": score,
            "payload": {"title": unit.title, "semantic_role": unit.semantic_role},
            "source": {"title": unit.title, "content": unit.content},
        }

    async def _document_index_hits(
        self, query: str, kb_id: str | None, roles: list[str], allowed_kbs: list[str]
    ) -> list[dict[str, Any]]:
        tokens = [tok.lower() for tok in re.split(r"\s+", query) if len(tok) >= 2]
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
            KnowledgeUnit.lifecycle.in_(
                [KnowledgeLifecycle.PUBLISHED.value, KnowledgeLifecycle.APPROVED.value]
            ),
        )
        if kb_id:
            unit_stmt = unit_stmt.where(KnowledgeUnit.kb_id == kb_id)
        elif allowed_kbs:
            unit_stmt = unit_stmt.where(KnowledgeUnit.kb_id.in_(allowed_kbs))
        if roles:
            unit_stmt = unit_stmt.where(KnowledgeUnit.semantic_role.in_(roles))
        units = (await self.session.execute(unit_stmt.limit(50))).scalars().all()
        return [self._unit_hit(unit, 1.2) for unit in units]


def _parse_intent(query: str, raw: str | None) -> QueryIntent:
    mapping = {
        "definition": QueryIntent.DEFINITION,
        "cause_analysis": QueryIntent.CAUSE,
        "cause": QueryIntent.CAUSE,
        "solution": QueryIntent.SOLUTION,
        "risk_analysis": QueryIntent.RISK,
        "risk": QueryIntent.RISK,
    }
    if raw in mapping:
        return mapping[raw]
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
        found.extend(re.findall(pattern, query, flags=re.IGNORECASE))
    return found or [query[:24]]


def _heuristic_answer(query: str, hits: list[dict[str, Any]], completeness: dict[str, Any]) -> str:
    if not hits:
        return "当前已发布知识中没有足够内容回答该问题。请先审核并发布相关 Knowledge Unit。"
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
    ]
    titles = {
        SemanticRole.DEFINITION.value: "定义",
        SemanticRole.ROOT_CAUSE.value: "问题原因",
        SemanticRole.PRINCIPLE.value: "原理",
        SemanticRole.SOLUTION.value: "解决方案",
        SemanticRole.CONSTRAINT.value: "设计约束",
        SemanticRole.EXAMPLE.value: "示例",
        SemanticRole.EXCEPTION.value: "例外",
    }
    for role in order:
        if role in grouped:
            parts.append(f"## {titles[role]}\n{grouped[role][0]}")
    missing = completeness.get("missing") or []
    if missing:
        parts.append("\n当前覆盖不完整，缺失：" + ", ".join(missing))
    parts.append("\n知识来源：\n" + "\n".join(f"- {h['title']} ({h.get('source_chapter') or 'N/A'})" for h in hits[:5]))
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
