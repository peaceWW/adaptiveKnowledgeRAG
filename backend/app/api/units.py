from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import BatchReviewAction, ReviewAction
from app.deps import get_stores
from app.domain.enums import KnowledgeLifecycle
from app.storage.db import get_session
from app.storage.models import Document, KnowledgeUnit, ReviewTask

router = APIRouter(prefix="/knowledge-units", tags=["knowledge-units"])


def _apply_unit_fields(
    unit: KnowledgeUnit,
    content: str | None = None,
    title: str | None = None,
    semantic_role: str | None = None,
    importance: str | None = None,
    confidence: float | None = None,
) -> None:
    if title is not None:
        unit.title = title.strip() or unit.title
    if semantic_role is not None:
        unit.semantic_role = semantic_role
    if importance is not None:
        unit.importance = importance
    if content is not None:
        unit.content = content
    if confidence is not None:
        unit.confidence = max(0.0, min(1.0, float(confidence)))


def apply_unit_review(
    unit: KnowledgeUnit,
    action: str,
    stores,
    comment: str = "",
    content: str | None = None,
    title: str | None = None,
    semantic_role: str | None = None,
    importance: str | None = None,
    confidence: float | None = None,
) -> None:
    _apply_unit_fields(unit, content, title, semantic_role, importance, confidence)
    if action == "save":
        if unit.lifecycle != KnowledgeLifecycle.PUBLISHED.value:
            return
    elif action == "accept":
        unit.lifecycle = KnowledgeLifecycle.PUBLISHED.value
        unit.source_level = "REVIEWED"
    elif action == "reject":
        unit.lifecycle = KnowledgeLifecycle.ARCHIVED.value
        stores.qdrant.delete(unit.id)
        return
    elif action == "edit":
        unit.lifecycle = KnowledgeLifecycle.PUBLISHED.value
        unit.source_level = "REVIEWED"
    else:
        raise HTTPException(400, "unknown action")
    if unit.lifecycle == KnowledgeLifecycle.PUBLISHED.value:
        vector = stores.gateway.embed([f"{unit.title}\n{unit.content}"])[0]
        stores.qdrant.upsert(
            unit.id,
            vector,
            {
                "kb_id": unit.kb_id,
                "knowledge_type": unit.knowledge_type,
                "semantic_role": unit.semantic_role,
                "domain": unit.domain,
                "concept_ids": unit.concepts,
                "source_level": unit.source_level,
                "lifecycle": unit.lifecycle,
                "version": unit.version,
                "title": unit.title,
                "content": unit.content[:2000],
            },
        )


async def _close_review_tasks(session: AsyncSession, unit_id: str, comment: str) -> None:
    result = await session.execute(select(ReviewTask).where(ReviewTask.ku_id == unit_id))
    for task in result.scalars().all():
        task.status = "done"
        task.comment = comment


@router.get("")
async def list_units(
    kb_id: str | None = None,
    document_id: str | None = None,
    lifecycle: str | None = None,
    role: str | None = None,
    enabled_only: bool = False,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(KnowledgeUnit)
    if kb_id:
        stmt = stmt.where(KnowledgeUnit.kb_id == kb_id)
    if document_id:
        stmt = stmt.where(KnowledgeUnit.document_id == document_id)
        doc = await session.get(Document, document_id)
        if doc and not doc.enabled and enabled_only:
            return []
    if lifecycle:
        stmt = stmt.where(KnowledgeUnit.lifecycle == lifecycle)
    if role:
        stmt = stmt.where(KnowledgeUnit.semantic_role == role)
    if enabled_only and not document_id:
        enabled_docs = select(Document.id).where(Document.enabled.is_(True))
        stmt = stmt.where(KnowledgeUnit.document_id.in_(enabled_docs))
    order = KnowledgeUnit.created_at.asc() if document_id else KnowledgeUnit.created_at.desc()
    result = await session.execute(stmt.order_by(order))
    return [_serialize(u) for u in result.scalars().all()]


def _document_original_text(doc: Document | None) -> str:
    if not doc:
        return ""
    structure = doc.structure or {}
    pages = structure.get("pages") or []
    texts = [str(page.get("text") or "") for page in pages if page.get("text")]
    return "\n\n".join(texts).strip()


@router.get("/{unit_id}")
async def get_unit(unit_id: str, session: AsyncSession = Depends(get_session)):
    unit = await session.get(KnowledgeUnit, unit_id)
    if not unit:
        raise HTTPException(404, "unit not found")
    source_text = ""
    original_text = ""
    filename = ""
    if unit.document_id:
        doc = await session.get(Document, unit.document_id)
        if doc:
            filename = doc.filename
            original_text = _document_original_text(doc)
            if doc.structure:
                pages = doc.structure.get("pages") or []
                for page in pages:
                    if int(page.get("page") or 0) == unit.source_page:
                        source_text = page.get("text") or ""
                        break
                if not source_text and pages:
                    source_text = pages[0].get("text") or ""
    return {
        **_serialize(unit),
        "source_text": source_text or unit.source_span or unit.content,
        "original_text": original_text or source_text or unit.source_span or unit.content,
        "filename": filename,
    }


@router.post("/batch-review")
async def batch_review(
    payload: BatchReviewAction,
    session: AsyncSession = Depends(get_session),
):
    stores = get_stores()
    if not payload.unit_ids:
        raise HTTPException(400, "unit_ids required")
    updated = []
    for unit_id in payload.unit_ids:
        unit = await session.get(KnowledgeUnit, unit_id)
        if not unit:
            continue
        if unit.document_id:
            doc = await session.get(Document, unit.document_id)
            if doc and not doc.enabled:
                raise HTTPException(400, f"文档未启用，无法审核：{doc.filename}")
        apply_unit_review(unit, payload.action, stores, comment=payload.comment)
        await _close_review_tasks(session, unit.id, payload.comment)
        updated.append(_serialize(unit))
    await session.commit()
    return {"count": len(updated), "units": updated}


@router.post("/{unit_id}/review")
async def review_unit(
    unit_id: str,
    payload: ReviewAction,
    session: AsyncSession = Depends(get_session),
):
    stores = get_stores()
    unit = await session.get(KnowledgeUnit, unit_id)
    if not unit:
        raise HTTPException(404, "unit not found")
    if unit.document_id:
        doc = await session.get(Document, unit.document_id)
        if doc and not doc.enabled:
            raise HTTPException(400, "文档未启用，无法进入知识审核")
    apply_unit_review(
        unit,
        payload.action,
        stores,
        comment=payload.comment,
        content=payload.content,
        title=payload.title,
        semantic_role=payload.semantic_role,
        importance=payload.importance,
        confidence=payload.confidence,
    )
    if payload.action != "save":
        await _close_review_tasks(session, unit_id, payload.comment)
    await session.commit()
    return _serialize(unit)


def _serialize(unit: KnowledgeUnit) -> dict:
    return {
        "id": unit.id,
        "kb_id": unit.kb_id,
        "document_id": unit.document_id,
        "title": unit.title,
        "content": unit.content,
        "semantic_role": unit.semantic_role,
        "importance": unit.importance,
        "knowledge_type": unit.knowledge_type,
        "concepts": unit.concepts,
        "parent_context": unit.parent_context,
        "source_chapter": unit.source_chapter,
        "source_section": unit.source_section,
        "source_page": unit.source_page,
        "source_span": unit.source_span,
        "version": unit.version,
        "confidence": unit.confidence,
        "lifecycle": unit.lifecycle,
        "source_level": unit.source_level,
    }
