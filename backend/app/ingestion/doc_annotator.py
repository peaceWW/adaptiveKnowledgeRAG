# 文档级千问标注：parse 后写 index_meta / index_keywords，替代检索中心人工归纳。
from __future__ import annotations

import json
from typing import Any

from app.observability.pipeline_log import step as pipeline_step
from app.prompts.loader import load_prompt
from app.retrieval.doc_index import normalize_keywords

DEFAULT_PROMPT = """你是芯片设计工程师，为资料库写检索元数据。不得编造。输出 JSON：
{"title":"","authors":[],"year":"","venue":"","domain":"","summary":"","knowledge_type":"","keywords":[{"keyword":"","weight":1.0}]}
"""
PREVIEW_CHARS = 8000
META_KEYS = ("title", "authors", "year", "venue", "domain", "summary", "knowledge_type")


def annotate_document_index(gateway, filename: str, text: str, existing_meta: dict | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """有模型时标注文档元数据与关键字；无 client 或 JSON 失败返回空，保留解析结果。"""
    if gateway is None or not getattr(gateway, "client", None):
        return {}, []
    prompt = _load_prompt()
    payload = {
        "filename": filename,
        "existing_metadata": existing_meta or {},
        "text_preview": (text or "")[:PREVIEW_CHARS],
    }
    result = gateway.chat_json(prompt, json.dumps(payload, ensure_ascii=False), temperature=0.0)
    if not isinstance(result, dict) or not result:
        pipeline_step("ingest", "doc_annotate", inputs={"filename": filename}, result={"ok": False})
        return {}, []
    meta = _meta_from_result(result)
    keywords = []
    for item in result.get("keywords") or []:
        if isinstance(item, str):
            keyword, weight = item.strip(), 1.0
        else:
            keyword = str(item.get("keyword") or "").strip()
            try:
                weight = float(item.get("weight") or 1.0)
            except (TypeError, ValueError):
                weight = 1.0
        if keyword:
            keywords.append({"keyword": keyword, "weight": min(max(weight, 0.1), 1.0), "source": "llm"})
    keywords = normalize_keywords(keywords)
    pipeline_step(
        "ingest",
        "doc_annotate",
        inputs={"filename": filename, "preview_chars": min(len(text or ""), PREVIEW_CHARS)},
        result={"ok": True, "meta_keys": sorted(meta), "keyword_count": len(keywords)},
    )
    return meta, keywords


def _meta_from_result(result: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in META_KEYS:
        value = result.get(key)
        if value in (None, "", []):
            continue
        meta[key] = value
    if meta:
        meta["annotated_by"] = "llm"
    return meta


def _load_prompt() -> str:
    return load_prompt("document-indexer", DEFAULT_PROMPT)
