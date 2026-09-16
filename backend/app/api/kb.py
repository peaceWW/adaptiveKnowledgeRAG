from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.documents import document_original_text
from app.api.schemas import CatalogNodeCreate, KnowledgeBaseCreate
from app.ingestion.catalog_sync import catalog_needs_rebuild, prune_orphan_auto_catalogs, public_related, sync_catalog_for_kb, unit_id_from_related
from app.storage.db import get_session
from app.storage.models import Document, KnowledgeBase, KnowledgeCatalog, KnowledgeUnit
from app.storage.paths import attach_image_refs

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("")
async def list_kb(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(KnowledgeBase).options(selectinload(KnowledgeBase.strategy)))
    items = []
    for kb in result.scalars().all():
        docs = await session.scalar(select(func.count(Document.id)).where(Document.kb_id == kb.id))
        units = await session.scalar(select(func.count(KnowledgeUnit.id)).where(KnowledgeUnit.kb_id == kb.id))
        items.append(
            {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "domain": kb.domain,
                "access_scope": kb.access_scope,
                "status": kb.status,
                "strategy": {
                    "id": kb.strategy.id,
                    "name": kb.strategy.name,
                    "knowledge_type": kb.strategy.knowledge_type,
                }
                if kb.strategy
                else None,
                "document_count": int(docs or 0),
                "unit_count": int(units or 0),
            }
        )
    return items


@router.post("")
async def create_kb(payload: KnowledgeBaseCreate, session: AsyncSession = Depends(get_session)):
    kb = KnowledgeBase(**payload.model_dump())
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return {"id": kb.id, "name": kb.name}


@router.get("/{kb_id}")
async def get_kb(kb_id: str, session: AsyncSession = Depends(get_session)):
    kb = await session.get(KnowledgeBase, kb_id, options=[selectinload(KnowledgeBase.strategy)])
    if not kb:
        return {}
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "domain": kb.domain,
        "strategy": kb.strategy.name if kb.strategy else None,
        "access_scope": kb.access_scope,
    }


def _catalog_item(node: KnowledgeCatalog, child_ids: set[str] | None = None) -> dict:
    children = child_ids or set()
    related = node.related_concepts or []
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "name": node.name,
        "path": node.path,
        "level": node.level,
        "related_concepts": public_related(related),
        "unit_id": unit_id_from_related(related),
        "is_leaf": node.id not in children,
    }


def _snippet_window(text: str, needle: str, radius: int = 220) -> str:
    if not text:
        return (needle or "")[:600]
    probe = (needle or "").strip()
    if not probe:
        return text[:600]
    idx = text.find(probe)
    if idx < 0:
        idx = text.find(probe[: min(len(probe), 48)])
    if idx < 0:
        return probe[:600]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(probe) + radius)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt = excerpt + "…"
    return excerpt


def _unit_matches_node(unit: KnowledgeUnit, node: KnowledgeCatalog) -> bool:
    """叶子优先按 catalog_id / __unit__ 精确对应，避免章节名模糊命中整篇。"""
    if unit.catalog_id == node.id:
        return True
    tagged = unit_id_from_related(node.related_concepts)
    return bool(tagged) and tagged == unit.id


def _descendant_path_pattern(path: str) -> str:
    """LIKE 前缀匹配子节点；转义 %/_，避免文章名里的下划线把别的节点也扫进来。"""
    escaped = str(path or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}/%"


def _quote_from_unit(unit: KnowledgeUnit, documents_map: dict[str, Document]) -> dict:
    """目录详情与图谱共用同一套依据字段，才能打开原文对照原 PDF。"""
    doc = documents_map.get(unit.document_id or "")
    original = document_original_text(doc) if doc else ""
    quote = unit.source_span or unit.content
    meta = attach_image_refs(unit.document_id, unit.unit_meta)
    doc_title = ""
    if doc:
        doc_title = str((doc.index_meta or {}).get("title") or doc.filename)
    return {
        "id": unit.id,
        "unit_id": unit.id,
        "title": unit.title,
        "role": unit.semantic_role,
        "semantic_role": unit.semantic_role,
        "lifecycle": unit.lifecycle,
        "filename": doc.filename if doc else "",
        "document_id": unit.document_id,
        "document_title": doc_title or (doc.filename if doc else "未关联文档"),
        "chapter": unit.source_chapter,
        "section": unit.source_section,
        "page": unit.source_page,
        "source_chapter": unit.source_chapter,
        "source_page": unit.source_page,
        "quote": quote,
        "original": _snippet_window(original, quote) if original else quote,
        "content": unit.content,
        "kind": meta.get("kind") or "",
        "latex": meta.get("latex") or "",
        "image_key": meta.get("image_key") or "",
        "image_url": meta.get("image_url") or "",
    }


@router.get("/{kb_id}/catalog")
async def catalog(kb_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(KnowledgeCatalog).where(KnowledgeCatalog.kb_id == kb_id).order_by(KnowledgeCatalog.level, KnowledgeCatalog.path)
    )
    nodes = result.scalars().all()
    if await prune_orphan_auto_catalogs(session, kb_id):
        await session.commit()
        result = await session.execute(
            select(KnowledgeCatalog).where(KnowledgeCatalog.kb_id == kb_id).order_by(KnowledgeCatalog.level, KnowledgeCatalog.path)
        )
        nodes = result.scalars().all()
    unit_count = int(await session.scalar(select(func.count(KnowledgeUnit.id)).where(KnowledgeUnit.kb_id == kb_id)) or 0)
    if catalog_needs_rebuild(nodes, unit_count):
        await sync_catalog_for_kb(session, kb_id)
        await session.commit()
        result = await session.execute(
            select(KnowledgeCatalog).where(KnowledgeCatalog.kb_id == kb_id).order_by(KnowledgeCatalog.level, KnowledgeCatalog.path)
        )
        nodes = result.scalars().all()
    parents = {n.parent_id for n in nodes if n.parent_id}
    return [_catalog_item(n, parents) for n in nodes]


@router.get("/{kb_id}/catalog/{node_id}")
async def catalog_node(kb_id: str, node_id: str, session: AsyncSession = Depends(get_session)):
    node = await session.get(KnowledgeCatalog, node_id)
    if not node or node.kb_id != kb_id:
        raise HTTPException(404, "catalog node not found")
    children = (
        await session.execute(
            select(KnowledgeCatalog).where(KnowledgeCatalog.parent_id == node.id).order_by(KnowledgeCatalog.path)
        )
    ).scalars().all()
    is_leaf = not children
    crumbs = []
    cursor = node
    seen: set[str] = set()
    while cursor and cursor.id not in seen:
        crumbs.append({"id": cursor.id, "name": cursor.name})
        seen.add(cursor.id)
        cursor = await session.get(KnowledgeCatalog, cursor.parent_id) if cursor.parent_id else None
    crumbs.reverse()

    units: list[KnowledgeUnit] = []
    documents_map: dict[str, Document] = {}
    quotes: list[dict] = []
    if is_leaf:
        tagged = unit_id_from_related(node.related_concepts)
        if tagged:
            unit = await session.get(KnowledgeUnit, tagged)
            units = [unit] if unit and unit.kb_id == kb_id else []
        else:
            all_units = (
                await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.kb_id == kb_id))
            ).scalars().all()
            units = [unit for unit in all_units if _unit_matches_node(unit, node)]
    else:
        # 章节/文章节点：汇总下属知识点，右侧详情才能像图谱一样直接看依据
        descendants = (
            await session.execute(
                select(KnowledgeCatalog).where(
                    KnowledgeCatalog.kb_id == kb_id,
                    KnowledgeCatalog.path.like(_descendant_path_pattern(node.path), escape="\\"),
                )
            )
        ).scalars().all()
        unit_ids = [unit_id_from_related(item.related_concepts) for item in descendants]
        unit_ids = [uid for uid in unit_ids if uid]
        if unit_ids:
            units = (
                await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids)))
            ).scalars().all()
    doc_ids = [unit.document_id for unit in units if unit.document_id]
    if doc_ids:
        docs = (
            await session.execute(select(Document).where(Document.id.in_(doc_ids)))
        ).scalars().all()
        documents_map = {doc.id: doc for doc in docs}
    quotes = [_quote_from_unit(unit, documents_map) for unit in units]

    visible_related = public_related(node.related_concepts)
    if is_leaf and units:
        overview = (units[0].content or "")[:500] or f"知识点：{node.name}"
    elif children:
        overview = f"「{node.name}」下有 {len(children)} 个{'知识点' if all(unit_id_from_related(child.related_concepts) for child in children) else '章节/条目'}。"
    else:
        overview = f"文章「{node.name}」，按章节展开查看抽取的知识点。"
    if visible_related and not is_leaf:
        overview += f" 标签：{'、'.join(visible_related[:8])}。"

    return {
        **_catalog_item(node),
        "is_leaf": is_leaf,
        "breadcrumb": crumbs,
        "children": [_catalog_item(child) for child in children],
        "overview": overview,
        "quotes": quotes,
        "documents": [
            {"id": doc.id, "filename": doc.filename, "status": doc.status}
            for doc in documents_map.values()
        ],
        "unit_count": len(units),
    }


@router.post("/{kb_id}/catalog")
async def create_catalog_node(kb_id: str, payload: CatalogNodeCreate, session: AsyncSession = Depends(get_session)):
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "knowledge base not found")
    parent = None
    level = 0
    path = payload.name
    if payload.parent_id:
        parent = await session.get(KnowledgeCatalog, payload.parent_id)
        if not parent or parent.kb_id != kb_id:
            raise HTTPException(404, "parent node not found")
        level = parent.level + 1
        path = f"{parent.path}/{payload.name}"
    node = KnowledgeCatalog(
        kb_id=kb_id,
        parent_id=payload.parent_id,
        name=payload.name,
        path=path,
        level=level,
        domain=kb.domain,
        related_concepts=payload.related_concepts,
    )
    session.add(node)
    await session.commit()
    await session.refresh(node)
    return _catalog_item(node)


@router.delete("/{kb_id}/catalog/{node_id}")
async def delete_catalog_node(kb_id: str, node_id: str, session: AsyncSession = Depends(get_session)):
    node = await session.get(KnowledgeCatalog, node_id)
    if not node or node.kb_id != kb_id:
        raise HTTPException(404, "catalog node not found")
    child = await session.scalar(select(func.count(KnowledgeCatalog.id)).where(KnowledgeCatalog.parent_id == node_id))
    if child:
        raise HTTPException(400, "请先删除子节点")
    await session.delete(node)
    await session.commit()
    return {"ok": True, "id": node_id}
