from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from urllib.parse import quote
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ConfirmStrategy
from app.api.pdf_source import page_text_layer, pdf_manifest, render_pdf_page
from app.api.units import apply_unit_review, _serialize as serialize_unit
from app.domain.extraction_policy import EXTRACTION_KINDS, extraction_kind, normalized_policy
from app.ingestion.catalog_sync import remove_catalog_for_document
from app.ingestion.configured_extraction import strategy_snapshot
from app.deps import get_stores
from app.domain.enums import DocumentStatus
from app.ingestion.workflow import IngestionWorkflow
from app.storage.db import get_session
from app.storage.models import Document, KnowledgeRelation, KnowledgeStrategy, KnowledgeUnit, ReviewTask, KnowledgeRole
from app.storage.paths import asset_key_allowed, original_object_key

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
        "extraction_summary": (doc.structure or {}).get("extraction_summary"),
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


@router.get("/{doc_id}/assets")
async def get_document_asset(
    doc_id: str,
    key: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    # 只放行本文件截图：新路径 images/{id}/，兼容旧 docs/{id}/
    if not asset_key_allowed(doc_id, key):
        raise HTTPException(400, "invalid asset key")
    stores = get_stores()
    data = stores.minio.get(key)
    if not data:
        raise HTTPException(404, "asset not found")
    return Response(content=data, media_type="image/png")


async def _stored_pdf(doc_id: str, session: AsyncSession) -> tuple[Document, bytes]:
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if not doc.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "该文档不是 PDF，请使用提取文本视图")
    try:
        raw = await run_in_threadpool(get_stores().minio.get, doc.object_key)
    except Exception as exc:
        raise HTTPException(503, "原始文件暂时无法读取，请检查文件存储服务后重试") from exc
    if not raw:
        raise HTTPException(404, "原始 PDF 文件不存在，请重新上传原文件")
    return doc, raw


@router.get("/{doc_id}/source")
async def get_pdf_source(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc, raw = await _stored_pdf(doc_id, session)
    manifest = await run_in_threadpool(pdf_manifest, raw)
    return {"document_id": doc.id, "filename": doc.filename, **manifest}


@router.get("/{doc_id}/pages/{page_number}/text")
async def get_pdf_page_text(doc_id: str, page_number: int,
                            session: AsyncSession = Depends(get_session)):
    """原稿选中复制：返回与页面图像对齐的文字层，扫描件可能为空。"""
    _, raw = await _stored_pdf(doc_id, session)
    return await run_in_threadpool(page_text_layer, raw, page_number)


@router.get("/{doc_id}/pages/{page_number}")
async def get_pdf_page(doc_id: str, page_number: int,
                       width: int = Query(1600, ge=600, le=3000),
                       session: AsyncSession = Depends(get_session)):
    _, raw = await _stored_pdf(doc_id, session)
    png = await run_in_threadpool(render_pdf_page, raw, page_number, width)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.get("/{doc_id}/original")
async def download_original_pdf(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc, raw = await _stored_pdf(doc_id, session)
    return Response(raw, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.filename, safe='')}",
        "Cache-Control": "private, no-store",
    })


@router.post("/upload")
async def upload_document(
    kb_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    stores = get_stores()
    raw = await file.read()
    filename = file.filename or "unknown"
    doc = Document(
        kb_id=kb_id,
        filename=filename,
        object_key="",
        mime_type=file.content_type or "application/octet-stream",
        status=DocumentStatus.UPLOADED.value,
        enabled=False,
        size_bytes=len(raw),
    )
    session.add(doc)
    await session.flush()
    # 先拿到文档 id，原文才能落到 originals/{kb}/{id}/，重启后按 object_key 读回
    object_key = original_object_key(kb_id, doc.id, filename)
    stores.minio.put(object_key, raw, file.content_type or "application/octet-stream")
    doc.object_key = object_key
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
    roles = (await session.execute(select(KnowledgeRole))).scalars().all()
    snapshot = strategy_snapshot(strategy, roles)
    # The selected strategy is authoritative; legacy wizard defaults must not overwrite it.
    if payload.knowledge_type:
        snapshot["knowledge_type"] = payload.knowledge_type
    doc.confirmed_strategy_id = strategy.id
    doc.status = DocumentStatus.EXTRACTING.value
    structure = dict(doc.structure or {})
    structure["process_config"] = {
        "chunk_policy": strategy.chunk_policy,
        "max_context_tokens": strategy.max_context_tokens,
        "strategy_snapshot": snapshot,
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


@router.get("/{doc_id}/extractions")
async def document_extractions(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    snapshot = ((doc.structure or {}).get("process_config") or {}).get("strategy_snapshot")
    if snapshot:
        snapshot = dict(snapshot)
        snapshot["extraction_policy"] = normalized_policy(snapshot.get("extraction_policy"))
    rows = (await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc_id)
                                  .order_by(KnowledgeUnit.created_at.asc()))).scalars().all() if doc.enabled else []
    units = [{**serialize_unit(unit), "extraction_kind": extraction_kind(unit)} for unit in rows]
    policy = (snapshot or {}).get("extraction_policy") or {}
    return {
        "document_id": doc.id, "strategy_snapshot": snapshot,
        "categories": [{**item, "count": sum(unit["extraction_kind"] == item["key"] for unit in units),
                        "enabled": policy.get(item["policy_key"]) if snapshot else None}
                       for item in EXTRACTION_KINDS],
        "units": units,
    }


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
    # 单元已删，再摘该文档自动生成的文章/章节/知识点目录，避免知识目录残留幽灵树
    await remove_catalog_for_document(session, doc.kb_id, doc.id)
    if doc.object_key:
        stores.minio.delete(doc.object_key)
    stores.minio.delete_prefix(f"images/{doc.id}")
    stores.minio.delete_prefix(f"docs/{doc.id}")
    stores.minio.delete_prefix(f"originals/{doc.kb_id}/{doc.id}")
    await stores.es.delete_document_index(doc_id)
    await session.delete(doc)
    await session.commit()
    return {"ok": True, "id": doc_id}
