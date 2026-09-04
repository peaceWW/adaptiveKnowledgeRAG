from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DocumentIndexUpdate, KeywordDelete, KeywordIndexItem, MetadataFieldDelete, PlannerUpdate
from app.deps import get_stores
from app.retrieval.doc_index import (
    document_index_blob,
    ensure_document_index,
    normalize_keywords,
    serialize_document_index,
    sync_document_index,
    unit_count_map,
)
from app.storage.db import get_session
from app.storage.models import Document, RetrievalPlannerConfig

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


async def _load_doc(session: AsyncSession, doc_id: str) -> Document:
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    return doc


@router.get("/indexes")
async def list_indexes(kb_id: str | None = None, q: str | None = None, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    stmt = select(Document).order_by(Document.created_at.desc())
    if kb_id:
        stmt = stmt.where(Document.kb_id == kb_id)
    docs = (await session.execute(stmt)).scalars().all()
    dirty_docs: list[Document] = []
    needle = (q or "").strip().lower()
    visible: list[Document] = []
    for doc in docs:
        if await ensure_document_index(session, doc, stores.es, commit=False):
            dirty_docs.append(doc)
        if needle and needle not in document_index_blob(doc):
            continue
        visible.append(doc)
    if dirty_docs:
        await session.commit()
        for doc in dirty_docs:
            await session.refresh(doc)
            await sync_document_index(stores.es, doc)
    counts = await unit_count_map(session, [doc.id for doc in visible])
    return [serialize_document_index(doc, counts.get(doc.id, 0)) for doc in visible]


@router.get("/indexes/{doc_id}")
async def get_index(doc_id: str, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await _load_doc(session, doc_id)
    await ensure_document_index(session, doc, stores.es)
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
