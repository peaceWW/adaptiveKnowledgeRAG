# 文档与截图的稳定访问地址：问答/审核用 URL，磁盘用相对 key。
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def public_asset_url(document_id: str, image_key: str) -> str:
    """前端与回答引用的图片地址，对应 GET /api/documents/{id}/assets。"""
    if not document_id or not image_key:
        return ""
    return f"/api/documents/{document_id}/assets?key={quote(image_key, safe='')}"


def image_refs(document_id: str, image_key: str) -> dict[str, str]:
    key = str(image_key or "")
    return {
        "image_key": key,
        "image_path": key,
        "image_url": public_asset_url(document_id, key) if key else "",
    }


def attach_image_refs(document_id: str | None, meta: dict | None) -> dict:
    """读出旧单元时用 image_key 补 image_url，避免库里只有文件名没有地址。"""
    data = dict(meta or {})
    key = str(data.get("image_key") or data.get("image_path") or "")
    if key and document_id:
        data.update(image_refs(document_id, key))
    return data


def original_object_key(kb_id: str, document_id: str, filename: str) -> str:
    """原文落盘用短名 original{ext}。目录已含文档 id，避免 IEEE 长文件名在 Windows 上超过 MAX_PATH。展示名仍用 Document.filename。"""
    name = (filename or "upload.bin").replace("\\", "/").split("/")[-1].replace("..", "")
    suffix = Path(name).suffix.lower()
    if len(suffix) > 16 or "/" in suffix or "\\" in suffix:
        suffix = ".bin"
    return f"originals/{kb_id}/{document_id}/original{suffix or '.bin'}"


def asset_key_allowed(document_id: str, key: str) -> bool:
    """只允许读本文件下的截图，兼容新 images/ 与旧 docs/ 前缀。"""
    if not document_id or not key or ".." in key:
        return False
    return key.startswith(f"images/{document_id}/") or key.startswith(f"docs/{document_id}/")
