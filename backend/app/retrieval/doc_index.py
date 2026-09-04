from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import Document, KnowledgeBase, KnowledgeUnit


def normalize_keywords(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, str):
            keyword = item.strip()
            weight, source = 1.0, "extracted"
        else:
            keyword = str(item.get("keyword") or "").strip()
            weight = float(item.get("weight") or 1.0)
            source = str(item.get("source") or "manual")
        key = keyword.lower()
        if not keyword or key in seen:
            continue
        seen.add(key)
        items.append({"keyword": keyword, "weight": weight, "source": source})
    return items


def document_index_body(doc: Document) -> dict[str, Any]:
    keywords = normalize_keywords(getattr(doc, "index_keywords", None))
    meta = dict(getattr(doc, "index_meta", None) or {})
    return {
        "filename": doc.filename,
        "kb_id": doc.kb_id,
        "keywords": [item["keyword"] for item in keywords],
        "keyword_weights": keywords,
        "metadata": meta,
        "status": doc.status,
        "enabled": bool(doc.enabled),
    }


def serialize_document_index(doc: Document, unit_count: int = 0) -> dict[str, Any]:
    keywords = normalize_keywords(getattr(doc, "index_keywords", None))
    meta = dict(getattr(doc, "index_meta", None) or {})
    return {
        "id": doc.id,
        "kb_id": doc.kb_id,
        "filename": doc.filename,
        "status": doc.status,
        "enabled": bool(doc.enabled),
        "keyword_count": len(keywords),
        "keywords": keywords,
        "metadata": meta,
        "unit_count": unit_count,
        "indexed": bool(keywords or meta),
    }


def document_index_blob(doc: Document) -> str:
    keywords = normalize_keywords(getattr(doc, "index_keywords", None))
    meta = dict(getattr(doc, "index_meta", None) or {})
    parts = [doc.filename or ""]
    parts.extend(item["keyword"] for item in keywords)
    for key, value in meta.items():
        parts.append(str(key))
        parts.append(str(value))
    return " ".join(parts).lower()


async def sync_document_index(es_store, doc: Document) -> None:
    if not es_store:
        return
    await es_store.upsert_document_index(doc.id, document_index_body(doc))


async def ensure_document_index(
    session: AsyncSession,
    doc: Document,
    es_store=None,
    commit: bool = True,
    force: bool = False,
) -> bool:
    raw_keywords = getattr(doc, "index_keywords", None)
    raw_meta = getattr(doc, "index_meta", None)
    keywords = normalize_keywords(raw_keywords)
    meta = dict(raw_meta or {})
    changed = False
    fill_keywords = raw_keywords is None or (force and not keywords)
    fill_meta = raw_meta is None or (force and not meta)
    if fill_keywords:
        units = (
            await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc.id))
        ).scalars().all()
        extracted: list[dict[str, Any]] = []
        for unit in units:
            extracted.extend(
                {"keyword": item, "weight": 0.8, "source": "extracted"}
                for item in (unit.concepts or [])
            )
        classification = doc.classification or {}
        if classification.get("knowledge_type"):
            extracted.append(
                {
                    "keyword": str(classification["knowledge_type"]),
                    "weight": 0.7,
                    "source": "extracted",
                }
            )
        keywords = normalize_keywords(extracted)
        doc.index_keywords = keywords
        changed = True
    if fill_meta:
        kb = await session.get(KnowledgeBase, doc.kb_id) if doc.kb_id else None
        classification = doc.classification or {}
        doc.index_meta = {
            "filename": doc.filename,
            "mime_type": doc.mime_type,
            "domain": (kb.domain if kb else "") or "semiconductor",
            "knowledge_type": classification.get("knowledge_type") or "",
            "strategy": doc.recommended_strategy or "",
            "status": doc.status,
            "enabled": bool(doc.enabled),
            "size_bytes": int(getattr(doc, "size_bytes", 0) or 0),
        }
        changed = True
    if changed and commit:
        await session.commit()
        await session.refresh(doc)
        await sync_document_index(es_store, doc)
    return changed


async def unit_count_map(session: AsyncSession, doc_ids: list[str]) -> dict[str, int]:
    if not doc_ids:
        return {}
    rows = (
        await session.execute(
            select(KnowledgeUnit.document_id, func.count(KnowledgeUnit.id)).where(
                KnowledgeUnit.document_id.in_(doc_ids)
            ).group_by(KnowledgeUnit.document_id)
        )
    ).all()
    return {str(doc_id): int(count or 0) for doc_id, count in rows}
