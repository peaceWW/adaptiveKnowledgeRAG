# 流水线关键步骤日志：统一 [AKRAG] 前缀，输出判定入参与结果，便于 grep 后台定位。
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("app.pipeline")

_MAX_STR = 240
_MAX_LIST = 12
_configured = False


def configure_pipeline_logging() -> None:
    """保证 app.pipeline 在 uvicorn 下也能打出 INFO，不依赖 root logger 级别。"""
    global _configured
    if _configured:
        return
    logger.setLevel(logging.INFO)
    if not any(getattr(handler, "_akrag_pipeline", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        handler._akrag_pipeline = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False
    _configured = True


def step(stage: str, name: str, *, inputs: Any = None, result: Any = None) -> None:
    """写一条关键判定日志。stage=ingest|retrieve，name 为步骤名。"""
    configure_pipeline_logging()
    payload: dict[str, Any] = {"stage": stage, "step": name}
    if inputs is not None:
        payload["in"] = clip(inputs)
    if result is not None:
        payload["out"] = clip(result)
    logger.info("[AKRAG] %s/%s %s", stage, name, json.dumps(payload, ensure_ascii=False, default=str))


def clip(value: Any, depth: int = 0) -> Any:
    """截断长文本与长列表，避免日志把整篇 PDF 打出来。"""
    if depth > 4:
        return "..."
    if isinstance(value, str):
        compact = " ".join(value.split())
        return compact if len(compact) <= _MAX_STR else compact[:_MAX_STR] + "…"
    if isinstance(value, dict):
        return {str(key): clip(item, depth + 1) for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        items = [clip(item, depth + 1) for item in list(value)[:_MAX_LIST]]
        extra = len(value) - _MAX_LIST
        if extra > 0:
            items.append(f"...+{extra}")
        return items
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return clip(str(value), depth)


def structure_digest(structure: dict[str, Any] | None) -> dict[str, Any]:
    """parse 结果摘要：体裁、页/章/图公式数量，不含正文。"""
    data = structure or {}
    meta = data.get("metadata") or {}
    return {
        "genre": data.get("genre"),
        "pages": len(data.get("pages") or []),
        "sections": [f"{item.get('id')} {item.get('title')}" for item in (data.get("sections") or [])[:12]],
        "section_count": len(data.get("sections") or []),
        "figures": [str(item.get("fig_id")) for item in (data.get("figures") or [])],
        "equations": [str(item.get("eq_id")) for item in (data.get("equations") or [])],
        "tables": [str(item.get("table_id")) for item in (data.get("tables") or [])],
        "citation_count": len(data.get("citations") or []),
        "parse_quality": data.get("parse_quality"),
        "title": (meta.get("title") or "")[:120],
        "doi": meta.get("doi") or "",
        "process_config": data.get("process_config") or {},
    }


def draft_digest(drafts: list[Any]) -> dict[str, Any]:
    """抽取草稿摘要：按 kind/role 计数 + 标题样例。"""
    kinds: dict[str, int] = {}
    roles: dict[str, int] = {}
    titles: list[str] = []
    for draft in drafts:
        meta = getattr(draft, "unit_meta", None) or {}
        kind = str(meta.get("kind") or "semantic")
        kinds[kind] = kinds.get(kind, 0) + 1
        role = getattr(getattr(draft, "semantic_role", None), "value", None) or str(
            getattr(draft, "semantic_role", "")
        )
        roles[role] = roles.get(role, 0) + 1
        titles.append(str(getattr(draft, "title", "") or "")[:80])
    return {"count": len(drafts), "kinds": kinds, "roles": roles, "titles": titles[:12]}


def hit_digest(hits: list[dict[str, Any]] | None, limit: int = 8) -> dict[str, Any]:
    """召回 hit 摘要：标题/角色/kind/通道/正文预览，便于对照答非所问。"""
    samples: list[dict[str, Any]] = []
    for hit in (hits or [])[:limit]:
        payload = hit.get("payload") or {}
        title = hit.get("title") or payload.get("title") or ""
        content = hit.get("content") or payload.get("content") or ""
        samples.append(
            {
                "id": str(hit.get("id") or "")[:12],
                "title": str(title)[:80],
                "kind": hit.get("kind") or payload.get("kind") or "",
                "role": hit.get("semantic_role") or payload.get("semantic_role") or "",
                "score": round(float(hit.get("score") or hit.get("fused_score") or 0), 4),
                "via": hit.get("via") or "",
                "anchor": hit.get("anchor") or payload.get("anchor") or "",
                "content": clip(str(content), 0),
            }
        )
    return {"count": len(hits or []), "samples": samples}
