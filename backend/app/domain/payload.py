from __future__ import annotations

from typing import Any

from app.storage.paths import attach_image_refs

KIND_EMBED_PREFIX = {"figure": "图:", "equation": "公式:"}


def unit_embed_text(unit: Any) -> str:
    """向量化文本：图/公式加前缀，避免和图注、公式原文在向量空间里混成普通段落。"""
    meta = getattr(unit, "unit_meta", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    kind = str(meta.get("kind") or "")
    title = str(getattr(unit, "title", "") or "")
    content = str(getattr(unit, "content", "") or "")
    blob = f"{title}\n{content}".strip()
    prefix = KIND_EMBED_PREFIX.get(kind, "")
    if prefix and not blob.startswith(prefix):
        return f"{prefix} {blob}".strip()
    return blob


def unit_vector_payload(unit: Any) -> dict[str, Any]:
    """写入 Qdrant 的检索载荷；带上 image_url，问答引用截图时不再只有文件名。"""
    meta = attach_image_refs(unit.document_id, unit.unit_meta)
    kind = str(meta.get("kind") or "")
    content = unit_embed_text(unit)
    return {
        "kb_id": unit.kb_id,
        "knowledge_type": unit.knowledge_type,
        "semantic_role": unit.semantic_role,
        "domain": unit.domain,
        "concept_ids": unit.concepts,
        "source_level": unit.source_level,
        "lifecycle": unit.lifecycle,
        "version": unit.version,
        "title": unit.title,
        "content": content[:2000],
        "kind": kind,
        "anchor": meta.get("anchor") or "",
        "document_id": unit.document_id or "",
        "parent_id": unit.parent_id or "",
        "source_page": unit.source_page or 0,
        "source_chapter": unit.source_chapter or "",
        "source_section": unit.source_section or "",
        "image_key": meta.get("image_key") or "",
        "image_url": meta.get("image_url") or "",
        "engineering_topic": meta.get("engineering_topic") or "",
    }
