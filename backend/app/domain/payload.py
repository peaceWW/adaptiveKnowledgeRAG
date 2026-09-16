from __future__ import annotations

from typing import Any

from app.storage.paths import attach_image_refs


def unit_vector_payload(unit: Any) -> dict[str, Any]:
    """写入 Qdrant 的检索载荷；带上 image_url，问答引用截图时不再只有文件名。"""
    meta = attach_image_refs(unit.document_id, unit.unit_meta)
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
        "content": (unit.content or "")[:2000],
        "kind": meta.get("kind") or "",
        "anchor": meta.get("anchor") or "",
        "document_id": unit.document_id or "",
        "parent_id": unit.parent_id or "",
        "source_page": unit.source_page or 0,
        "source_chapter": unit.source_chapter or "",
        "source_section": unit.source_section or "",
        "image_key": meta.get("image_key") or "",
        "image_url": meta.get("image_url") or "",
    }
