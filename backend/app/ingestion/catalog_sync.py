# 抽取完成后按「文章 → 章节 → 知识点叶子」写入知识目录，供思维导图展示。
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.pipeline_log import step as pipeline_step
from app.storage.models import Document, KnowledgeCatalog, KnowledgeUnit

AUTO_TAG = "__auto__"
DOC_PREFIX = "__doc__:"
UNIT_PREFIX = "__unit__:"
KIND_PREFIX = "__kind__:"
LEGACY_ROOTS = ("主题", "本体")


def _safe_name(value: str, fallback: str = "未命名") -> str:
    """去掉会破坏 path 层级的斜杠；Gb/s 改成全角，避免被当成多级目录。"""
    text = " ".join(str(value or "").replace("\\", " ").split()).strip()
    text = text.replace("/", "／")
    return (text[:80] or fallback)


def _doc_tag(document_id: str) -> str:
    return f"{DOC_PREFIX}{document_id}"


def _unit_tag(unit_id: str) -> str:
    return f"{UNIT_PREFIX}{unit_id}"


def _kind_tag(kind: str) -> str:
    return f"{KIND_PREFIX}{kind}"


def public_related(related: list | None) -> list[str]:
    """目录展示用标签，去掉内部标记。"""
    return [str(item) for item in (related or []) if item and not str(item).startswith("__")]


def unit_id_from_related(related: list | None) -> str:
    for item in related or []:
        text = str(item)
        if text.startswith(UNIT_PREFIX):
            return text[len(UNIT_PREFIX) :]
    return ""


def document_catalog_title(doc: Document) -> str:
    """文章节点名：优先千问/PDF 标题，否则用文件名。"""
    meta = dict(getattr(doc, "index_meta", None) or {})
    structure_meta = ((doc.structure or {}).get("metadata") if doc.structure else {}) or {}
    title = str(meta.get("title") or structure_meta.get("title") or "").strip()
    if not title or title == doc.filename:
        title = Path(doc.filename or "").stem
    return _safe_name(title, "未命名文档")


def _heading_already_has_id(heading: str, section_id: str) -> bool:
    if not heading or not section_id:
        return False
    head, sid = heading.lower(), section_id.lower()
    return head == sid or head.startswith(f"{sid} ") or head.startswith(f"{sid}.") or head.startswith(f"{sid}．")


def _doc_sections(doc: Document) -> list[dict[str, Any]]:
    """沿用解析出的章节顺序，作为导图中间层。"""
    sections = []
    for item in (doc.structure or {}).get("sections") or []:
        section_id = str(item.get("id") or "").strip()
        heading = str(item.get("title") or "").strip()
        if heading and section_id and not _heading_already_has_id(heading, section_id):
            name = _safe_name(f"{section_id} {heading}")
        else:
            name = _safe_name(heading or section_id or "正文", "正文")
        sections.append(
            {
                "id": section_id,
                "title": heading,
                "name": name,
                "page": int(item.get("page") or 0),
            }
        )
    return sections


def _section_name(unit: KnowledgeUnit, sections: list[dict[str, Any]]) -> str:
    """把知识点挂到所属章节：先对 section_id/标题，再按页码落到最近的章。"""
    meta = unit.unit_meta or {}
    section_id = str(meta.get("section_id") or unit.source_chapter or "").strip()
    heading = str(unit.source_section or "").strip()
    for section in sections:
        if section_id and section_id.lower() == str(section["id"]).lower():
            return section["name"]
        if heading and heading.lower() == str(section["title"]).lower():
            return section["name"]
        if heading and heading.lower() in str(section["name"]).lower():
            return section["name"]
    if heading or section_id:
        if heading and section_id and not _heading_already_has_id(heading, section_id):
            return _safe_name(f"{section_id} {heading}")
        return _safe_name(heading or section_id, "正文")
    page = int(getattr(unit, "source_page", 0) or 0)
    chosen = ""
    for section in sections:
        if section["page"] and page and section["page"] <= page:
            chosen = section["name"]
    return chosen or "正文"


def build_catalog_plan(doc: Document, units: list[KnowledgeUnit]) -> dict[str, Any]:
    """文章为根，章节为中间层，每个 Knowledge Unit 单独成为叶子。"""
    title = document_catalog_title(doc)
    tag = _doc_tag(doc.id)
    sections = _doc_sections(doc)
    nodes: dict[str, dict[str, Any]] = {}
    assignments: dict[str, str] = {}

    def add_node(path: str, name: str, related: list[str] | None = None) -> None:
        current = nodes.get(path) or {"path": path, "name": name, "related": [AUTO_TAG, tag]}
        merged = list(current.get("related") or [])
        for item in related or []:
            if item and item not in merged:
                merged.append(item)
        if AUTO_TAG not in merged:
            merged.insert(0, AUTO_TAG)
        if tag not in merged:
            merged.append(tag)
        current["name"] = name
        current["related"] = merged
        nodes[path] = current

    add_node(title, title, [_kind_tag("document")])
    grouped: dict[str, list[KnowledgeUnit]] = defaultdict(list)
    for unit in units:
        if (unit.unit_meta or {}).get("stub"):
            continue
        grouped[_section_name(unit, sections)].append(unit)

    ordered: list[str] = []
    seen: set[str] = set()
    for section in sections:
        name = section["name"]
        if name in grouped and name not in seen:
            ordered.append(name)
            seen.add(name)
    leftovers = [name for name in grouped if name not in seen]
    leftovers.sort(key=lambda name: (min((int(u.source_page or 0) or 999) for u in grouped[name]), name))
    ordered.extend(leftovers)

    for index, section_name in enumerate(ordered, start=1):
        section_path = f"{title}/{index:02d} {section_name}"
        add_node(section_path, section_name, [_kind_tag("section")])
        group = grouped[section_name]
        group.sort(key=lambda unit: (int(unit.source_page or 0), str(unit.title or "")))
        used_names: dict[str, int] = {}
        for unit in group:
            leaf_name = _safe_name(unit.title or "知识点", "知识点")
            used_names[leaf_name] = used_names.get(leaf_name, 0) + 1
            if used_names[leaf_name] > 1:
                leaf_name = f"{leaf_name}（{used_names[leaf_name]}）"
            leaf_path = f"{section_path}/{leaf_name}"
            add_node(
                leaf_path,
                leaf_name,
                [
                    _kind_tag("unit"),
                    _unit_tag(unit.id),
                    str(getattr(unit, "semantic_role", "") or ""),
                    *[str(item) for item in (unit.concepts or [])[:8]],
                ],
            )
            assignments[unit.id] = leaf_path

    return {"nodes": list(nodes.values()), "assignments": assignments, "title": title}


def catalog_needs_rebuild(nodes: list[KnowledgeCatalog], unit_count: int) -> bool:
    """空树、旧版主题/本体树、或还没有知识点叶子时，用章节树重建。"""
    if not unit_count:
        return False
    if not nodes:
        return True
    has_unit_leaf = any(unit_id_from_related(node.related_concepts) for node in nodes)
    has_legacy = any(str(node.path or "").split("/")[0] in LEGACY_ROOTS for node in nodes)
    return (not has_unit_leaf) or has_legacy


async def _prune_auto_nodes(session: AsyncSession, kb_id: str, document_id: str | None = None, legacy: bool = False) -> int:
    """删除自动生成的旧节点（先叶子后祖先），避免和手搓目录冲突。"""
    nodes = (
        await session.execute(select(KnowledgeCatalog).where(KnowledgeCatalog.kb_id == kb_id))
    ).scalars().all()
    doomed: list[KnowledgeCatalog] = []
    doc_tag = _doc_tag(document_id) if document_id else ""
    for node in nodes:
        related = node.related_concepts or []
        auto = AUTO_TAG in related
        if document_id and auto and doc_tag in related:
            doomed.append(node)
            continue
        if legacy and auto and str(node.path or "").split("/")[0] in LEGACY_ROOTS:
            doomed.append(node)
    if not doomed:
        return 0
    ids = [node.id for node in doomed]
    await session.execute(update(KnowledgeUnit).where(KnowledgeUnit.catalog_id.in_(ids)).values(catalog_id=None))
    for node in sorted(doomed, key=lambda item: (-int(item.level or 0), item.path or "")):
        await session.delete(node)
    await session.flush()
    return len(doomed)


async def sync_catalog_from_document(session: AsyncSession, doc: Document, units: list[KnowledgeUnit]) -> dict[str, Any]:
    """按章节重写该文档的自动目录，并把 unit.catalog_id 指到对应知识点叶子。"""
    if not doc.kb_id or not units:
        return {"ok": False, "nodes": 0}
    await _prune_auto_nodes(session, doc.kb_id, document_id=doc.id, legacy=True)
    plan = build_catalog_plan(doc, units)
    existing = (
        await session.execute(select(KnowledgeCatalog).where(KnowledgeCatalog.kb_id == doc.kb_id))
    ).scalars().all()
    path_to_node = {node.path: node for node in existing}
    created = 0
    for spec in sorted(plan["nodes"], key=lambda item: item["path"].count("/")):
        path = spec["path"]
        parent_path = "/".join(path.split("/")[:-1])
        parent = path_to_node.get(parent_path)
        node = path_to_node.get(path)
        if node:
            node.name = spec["name"]
            node.related_concepts = _merge_related(node.related_concepts, spec["related"])
            continue
        node = KnowledgeCatalog(
            kb_id=doc.kb_id,
            parent_id=parent.id if parent else None,
            name=spec["name"],
            path=path,
            level=path.count("/"),
            domain="semiconductor",
            related_concepts=spec["related"],
        )
        session.add(node)
        await session.flush()
        path_to_node[path] = node
        created += 1
    for unit in units:
        path = plan["assignments"].get(unit.id)
        node = path_to_node.get(path or "")
        if node:
            unit.catalog_id = node.id
    pipeline_step(
        "ingest",
        "catalog_sync",
        inputs={"document_id": doc.id, "kb_id": doc.kb_id, "filename": doc.filename},
        result={"title": plan["title"], "nodes": len(plan["nodes"]), "created": created, "assigned": len(plan["assignments"])},
    )
    return {"ok": True, "nodes": len(plan["nodes"]), "created": created, "title": plan["title"]}


async def sync_catalog_for_kb(session: AsyncSession, kb_id: str) -> dict[str, Any]:
    """按库内已抽取文档重建章节导图；打开知识目录即可看到文章结构。"""
    docs = (await session.execute(select(Document).where(Document.kb_id == kb_id))).scalars().all()
    total = 0
    for doc in docs:
        units = (
            await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc.id))
        ).scalars().all()
        if not units:
            continue
        result = await sync_catalog_from_document(session, doc, list(units))
        total += int(result.get("created") or 0)
    return {"ok": True, "created": total, "documents": len(docs)}


def _merge_related(existing: list | None, extra: list[str]) -> list[str]:
    merged: list[str] = []
    for item in list(existing or []) + list(extra or []):
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
    return merged
