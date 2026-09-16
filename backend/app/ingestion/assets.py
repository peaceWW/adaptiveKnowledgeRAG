# 把 PDF 裁出的图/公式/表 PNG 落到固定目录，并写上可引用的 image_url。
from __future__ import annotations

from typing import Any

from app.ingestion.academic_parse import render_region_png
from app.storage.paths import image_refs


def asset_key(document_id: str, kind: str, anchor: str) -> str:
    safe = str(anchor).replace(":", "_").replace("[", "").replace("]", "")
    return f"images/{document_id}/{kind}_{safe}.png"


def put_png(minio: Any, key: str, data: bytes) -> str:
    if minio is not None and data:
        minio.put(key, data, "image/png")
    return key


def materialize_paper_assets(minio: Any, document_id: str, raw: bytes, structure: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return structure
    for fig in structure.get("figures") or []:
        bbox = fig.get("bbox") or []
        png = render_region_png(raw, int(fig.get("page") or 1), [float(v) for v in bbox]) if len(bbox) == 4 else b""
        if png:
            key = asset_key(document_id, "fig", str(fig.get("fig_id") or "unknown"))
            put_png(minio, key, png)
            fig.update(image_refs(document_id, key))
        else:
            fig.setdefault("image_key", "")
            fig.setdefault("image_url", "")
            fig.setdefault("image_path", "")
    for eq in structure.get("equations") or []:
        bbox = eq.get("bbox") or []
        png = render_region_png(raw, int(eq.get("page") or 1), [float(v) for v in bbox]) if len(bbox) == 4 else b""
        if png:
            key = asset_key(document_id, "eq", str(eq.get("eq_id") or "unknown"))
            put_png(minio, key, png)
            eq.update(image_refs(document_id, key))
        else:
            eq.setdefault("image_key", "")
            eq.setdefault("image_url", "")
            eq.setdefault("image_path", "")
    for table in structure.get("tables") or []:
        bbox = table.get("bbox") or []
        png = render_region_png(raw, int(table.get("page") or 1), [float(v) for v in bbox]) if len(bbox) == 4 else b""
        if png:
            key = asset_key(document_id, "table", str(table.get("table_id") or "unknown"))
            put_png(minio, key, png)
            table.update(image_refs(document_id, key))
        else:
            table.setdefault("image_key", "")
            table.setdefault("image_url", "")
            table.setdefault("image_path", "")
    return structure
