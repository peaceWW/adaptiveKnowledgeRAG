from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ConfirmStrategy
from app.api.units import apply_unit_review
from app.deps import get_stores
from app.domain.enums import DocumentStatus
from app.ingestion.workflow import IngestionWorkflow
from app.storage.db import get_session
from app.storage.models import Document, KnowledgeRelation, KnowledgeStrategy, KnowledgeUnit, ReviewTask

router = APIRouter(prefix="/documents", tags=["documents"])


def document_original_text(doc: Document) -> str:
    structure = doc.structure or {}
    pages = structure.get("pages") or []
    texts = [str(page.get("text") or "") for page in pages if page.get("text")]
    return "\n\n".join(texts).strip()


def _serialize(doc: Document, unit_count: int = 0) -> dict:
    return {
        "id": doc.id,
        "kb_id": doc.kb_id,
        "filename": doc.filename,
        "status": doc.status,
        "enabled": bool(doc.enabled),
        "parse_progress": doc.parse_progress,
        "classification": doc.classification,
        "recommended_strategy": doc.recommended_strategy,
        "confirmed_strategy_id": doc.confirmed_strategy_id,
        "unit_count": unit_count,
        "error_message": doc.error_message,
        "size_bytes": int(getattr(doc, "size_bytes", 0) or 0),
        "mime_type": doc.mime_type,
    }


@router.get("")
async def list_documents(
    kb_id: str | None = None,
    enabled: bool | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Document).order_by(Document.created_at.desc())
    if kb_id:
        stmt = stmt.where(Document.kb_id == kb_id)
    if enabled is not None:
        stmt = stmt.where(Document.enabled.is_(enabled))
    result = await session.execute(stmt)
    docs = result.scalars().all()
    items = []
    for doc in docs:
        count = await session.scalar(
            select(func.count(KnowledgeUnit.id)).where(KnowledgeUnit.document_id == doc.id)
        )
        items.append(_serialize(doc, int(count or 0)))
    return items


@router.get("/{doc_id}")
async def get_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    count = await session.scalar(
        select(func.count(KnowledgeUnit.id)).where(KnowledgeUnit.document_id == doc.id)
    )
    return {
        **_serialize(doc, int(count or 0)),
        "structure": doc.structure,
        "original_text": document_original_text(doc),
    }


@router.post("/upload")
async def upload_document(
    kb_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    stores = get_stores()
    raw = await file.read()
    object_key = f"{kb_id}/{file.filename}"
    stores.minio.put(object_key, raw, file.content_type or "application/octet-stream")
    doc = Document(
        kb_id=kb_id,
        filename=file.filename or "unknown",
        object_key=object_key,
        mime_type=file.content_type or "application/octet-stream",
        status=DocumentStatus.UPLOADED.value,
        enabled=False,
        size_bytes=len(raw),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    workflow = IngestionWorkflow(session, stores.gateway, stores.minio, stores.qdrant, stores.es, stores.neo4j)
    await workflow.run_analyze(doc.id, doc.filename, raw)
    await session.refresh(doc)
    return _serialize(doc)


@router.post("/{doc_id}/confirm-strategy")
async def confirm_strategy(
    doc_id: str,
    payload: ConfirmStrategy,
    session: AsyncSession = Depends(get_session),
):
    stores = get_stores()
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    strategy = await session.get(KnowledgeStrategy, payload.strategy_id)
    if not strategy:
        raise HTTPException(404, "strategy not found")
    doc.confirmed_strategy_id = strategy.id
    doc.status = DocumentStatus.EXTRACTING.value
    structure = dict(doc.structure or {})
    structure["process_config"] = {
        "chunk_policy": payload.chunk_policy or "semantic_unit",
        "max_context_tokens": payload.max_context_tokens or 2000,
        "require_human_review": payload.require_human_review,
        "auto_enable": payload.auto_enable,
    }
    doc.structure = structure
    await session.commit()
    raw = stores.minio.get(doc.object_key)
    workflow = IngestionWorkflow(session, stores.gateway, stores.minio, stores.qdrant, stores.es, stores.neo4j)
    knowledge_type = payload.knowledge_type or strategy.knowledge_type
    await workflow.run_extract(doc.id, doc.filename, raw, knowledge_type)
    await session.refresh(doc)
    if payload.auto_enable and doc.status in {DocumentStatus.REVIEW.value, DocumentStatus.INDEXED.value}:
        doc.enabled = True
        await session.commit()
        await session.refresh(doc)
    return _serialize(doc)


@router.post("/{doc_id}/enable")
async def enable_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    if doc.status not in {DocumentStatus.REVIEW.value, DocumentStatus.INDEXED.value}:
        raise HTTPException(400, "请先完成知识抽取，再启用文档进入审核")
    doc.enabled = True
    units = (
        await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc.id))
    ).scalars().all()
    for unit in units:
        if unit.lifecycle == "ARCHIVED":
            unit.lifecycle = "PENDING_REVIEW"
    await session.commit()
    return _serialize(doc, len(units))


@router.post("/{doc_id}/disable")
async def disable_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    doc.enabled = False
    units = (
        await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc.id))
    ).scalars().all()
    for unit in units:
        apply_unit_review(unit, "reject", stores, comment="document disabled")
    result = await session.execute(select(ReviewTask).where(ReviewTask.document_id == doc.id))
    for task in result.scalars().all():
        task.status = "done"
        task.comment = "document disabled"
    await session.commit()
    return _serialize(doc, len(units))


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    units = (
        await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc.id))
    ).scalars().all()
    unit_ids = [unit.id for unit in units]
    if unit_ids:
        tasks = await session.execute(select(ReviewTask).where(ReviewTask.ku_id.in_(unit_ids)))
        for task in tasks.scalars().all():
            await session.delete(task)
        rels = await session.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.from_id.in_(unit_ids) | KnowledgeRelation.to_id.in_(unit_ids)
            )
        )
        for rel in rels.scalars().all():
            await session.delete(rel)
        for unit in units:
            stores.qdrant.delete(unit.id)
            await stores.es.delete(unit.id)
            await session.delete(unit)
    leftover_tasks = await session.execute(select(ReviewTask).where(ReviewTask.document_id == doc.id))
    for task in leftover_tasks.scalars().all():
        await session.delete(task)
    await stores.es.delete_document_index(doc_id)
    await session.delete(doc)
    await session.commit()
    return {"ok": True, "id": doc_id}
