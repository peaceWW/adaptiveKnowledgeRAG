from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from time import perf_counter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DocumentIndexUpdate, KeywordDelete, KeywordIndexItem, MetadataFieldDelete, PlannerUpdate
from app.deps import get_stores, current_user
from app.domain.enums import RETRIEVAL_LIFECYCLES
from app.retrieval.workflow import QueryWorkflow
from app.retrieval.doc_index import (
    document_index_blob,
    ensure_document_index,
    normalize_keywords,
    serialize_document_index,
    sync_document_index,
    unit_count_map,
)
from app.storage.db import get_session
from app.storage.models import Document, RetrievalPlannerConfig, KnowledgeUnit, KnowledgeBase, KnowledgeAcl, User

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


class RetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_id: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        if not value.strip():
            raise ValueError("请输入需要检索的问题")
        return value.strip()


@router.post("/test")
async def test_retrieval(payload: RetrievalTestRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)):
    kb = await session.get(KnowledgeBase, payload.kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    rules = (await session.execute(select(KnowledgeAcl).where(KnowledgeAcl.kb_id == kb.id))).scalars().all()
    permitted = user.role == "admin" or kb.access_scope == "public"
    permitted |= kb.access_scope == "department" and bool(user.department) and kb.department == user.department
    permitted |= kb.access_scope == "project" and bool(user.project) and kb.project == user.project
    permitted |= any(r.permission in {"read", "write", "admin"} and (
        (r.principal_type == "user" and r.principal_id == user.id) or
        (r.principal_type == "role" and r.principal_id == user.role)
    ) for r in rules)
    if not permitted:
        raise HTTPException(403, "无权检索该知识库")
    stores = get_stores()
    workflow = QueryWorkflow(session, stores.gateway, stores.qdrant, stores.es, stores.neo4j)
    started = perf_counter()
    state = {"query": payload.query, "kb_id": payload.kb_id, "user_id": user.id}
    stages = []
    for key, label in [("understand", "理解问题"), ("plan", "确定检索范围"), ("retrieve", "召回、重排与关联展开")]:
        step_start = perf_counter()
        state = await getattr(workflow, key)(state)
        stages.append({"key": key, "label": label, "elapsed_ms": int((perf_counter() - step_start) * 1000)})
    hits = state.get("hits") or []
    docs = {d.id: d for d in (await session.execute(select(Document).where(Document.kb_id == kb.id))).scalars().all()}
    visible = []
    for hit in hits[:payload.top_k]:
        item = dict(hit)
        doc = docs.get(item.get("document_id"))
        item["filename"] = doc.filename if doc else ""
        item["document_title"] = ((doc.index_meta or {}).get("title") or doc.filename) if doc else "未关联文档"
        visible.append(item)
    return {"query": payload.query, "kb_id": kb.id, "kb_name": kb.name,
            "hits": visible, "total": len(hits), "stages": stages,
            "elapsed_ms": int((perf_counter() - started) * 1000),
            "understanding": state.get("understanding") or {}, "plan": state.get("plan") or {},
            "retrieval": state.get("retrieval") or {},
            "services": {"vector": bool(getattr(stores.qdrant, "available", False)),
                         "keyword": bool(getattr(stores.es, "available", False)),
                         "graph": bool(getattr(stores.neo4j, "available", False)),
                         "model": bool(getattr(stores.gateway, "client", None))}}


async def _load_doc(session: AsyncSession, doc_id: str) -> Document:
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    return doc


@router.get("/indexes")
async def list_indexes(kb_id: str | None = None, q: str | None = None, session: AsyncSession = Depends(get_session)):
    stmt = select(Document).order_by(Document.created_at.desc())
    if kb_id:
        stmt = stmt.where(Document.kb_id == kb_id)
    docs = (await session.execute(stmt)).scalars().all()
    needle = (q or "").strip().lower()
    visible: list[Document] = []
    for doc in docs:
        if needle and needle not in document_index_blob(doc):
            continue
        visible.append(doc)
    counts = await unit_count_map(session, [doc.id for doc in visible])
    ready = dict((await session.execute(select(KnowledgeUnit.document_id, func.count(KnowledgeUnit.id)).where(
        KnowledgeUnit.document_id.in_([d.id for d in visible]), KnowledgeUnit.lifecycle.in_(list(RETRIEVAL_LIFECYCLES))
    ).group_by(KnowledgeUnit.document_id))).all())
    return [{**serialize_document_index(doc, counts.get(doc.id, 0)), "retrievable_count": ready.get(doc.id, 0)} for doc in visible]


@router.get("/indexes/{doc_id}")
async def get_index(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await _load_doc(session, doc_id)
    counts = await unit_count_map(session, [doc.id])
    return serialize_document_index(doc, counts.get(doc.id, 0))


@router.put("/indexes/{doc_id}")
async def update_index(doc_id: str, payload: DocumentIndexUpdate, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    if payload.keywords is not None:
        doc.index_keywords = normalize_keywords([item.model_dump() for item in payload.keywords])
    if payload.metadata is not None:
        doc.index_meta = {str(key).strip(): value for key, value in payload.metadata.items() if str(key).strip()}
    await session.commit()
    await session.refresh(doc)
    await sync_document_index(stores.es, doc)
    counts = await unit_count_map(session, [doc.id])
    return serialize_document_index(doc, counts.get(doc.id, 0))


@router.post("/indexes/{doc_id}/keywords")
async def add_keyword(doc_id: str, payload: KeywordIndexItem, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    doc.index_keywords = normalize_keywords(normalize_keywords(doc.index_keywords) + [payload.model_dump()])
    await session.commit()
    await session.refresh(doc)
    await sync_document_index(stores.es, doc)
    return serialize_document_index(doc)


@router.delete("/indexes/{doc_id}/keywords")
async def delete_keyword(doc_id: str, payload: KeywordDelete, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    target = payload.keyword.strip().lower()
    doc.index_keywords = [
        item for item in normalize_keywords(doc.index_keywords) if item["keyword"].lower() != target
    ]
    await session.commit()
    await session.refresh(doc)
    await sync_document_index(stores.es, doc)
    return serialize_document_index(doc)


@router.delete("/indexes/{doc_id}/metadata")
async def delete_metadata_field(doc_id: str, payload: MetadataFieldDelete, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    meta = dict(getattr(doc, "index_meta", None) or {})
    meta.pop(payload.key, None)
    doc.index_meta = meta
    await session.commit()
    await session.refresh(doc)
    await sync_document_index(stores.es, doc)
    return serialize_document_index(doc)


@router.post("/indexes/{doc_id}/reindex")
async def reindex_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    await ensure_document_index(session, doc, stores.es, force=True)
    await sync_document_index(stores.es, doc)
    counts = await unit_count_map(session, [doc.id])
    return {"ok": True, **serialize_document_index(doc, counts.get(doc.id, 0))}


@router.delete("/indexes/{doc_id}")
async def clear_index(doc_id: str, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    doc.index_keywords = []
    doc.index_meta = {}
    await session.commit()
    await stores.es.delete_document_index(doc_id)
    return {"ok": True, "id": doc_id}


@router.get("/planners")
async def list_planners(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(RetrievalPlannerConfig))
    return [
        {
            "id": p.id,
            "query_type": p.query_type,
            "steps": p.steps,
            "completeness_threshold": p.completeness_threshold,
            "secondary_retrieval": p.secondary_retrieval,
        }
        for p in result.scalars().all()
    ]


@router.put("/planners/{planner_id}")
async def update_planner(
    planner_id: str,
    payload: PlannerUpdate,
    session: AsyncSession = Depends(get_session),
):
    planner = await session.get(RetrievalPlannerConfig, planner_id)
    if not planner:
        planner = RetrievalPlannerConfig(id=planner_id, query_type=payload.query_type)
        session.add(planner)
    planner.query_type = payload.query_type
    planner.steps = payload.steps
    planner.completeness_threshold = payload.completeness_threshold
    planner.secondary_retrieval = payload.secondary_retrieval
    await session.commit()
    return {"id": planner.id, "query_type": planner.query_type, "steps": planner.steps}
