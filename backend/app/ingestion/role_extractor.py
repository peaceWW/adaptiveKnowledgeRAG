# 按策略快照 Role 分窗口调用 LLM 抽文本 Knowledge Unit；图/公式/表/引用仍走解析清单。
from __future__ import annotations

import json

from app.domain.enums import KnowledgeType, SemanticRole
from app.domain.extraction_policy import normalized_policy
from app.domain.roles import ROLE_LABELS
from app.domain.strategy import DocumentContext, KnowledgeUnitDraft
from app.ingestion.configured_extraction import split_content
from app.ingestion.extractor import _extract_concepts
from app.observability.pipeline_log import draft_digest, step as pipeline_step
from app.prompts.loader import load_prompt

PROMPT_ID = "role-extractor"
DEFAULT_PROMPT = """你是芯片设计工程师，根据允许的 Role 从窗口原文抽取 Knowledge Unit。
不得引入原文没有的事实。每条必须带 source_span。输出 JSON：
{"units":[{"title":"","semantic_role":"","content":"","source_span":"","concepts":[],"importance":"core"}]}
"""
SKIP_SECTION_PREFIXES = ("reference", "bibliography", "acknowledgment")


def extract_role_units(context: DocumentContext, snapshot: dict, knowledge_type: KnowledgeType) -> list[KnowledgeUnitDraft]:
    """有真实模型时按快照 Role 抽文本单元；无 client 或全部失败返回空，由调用方退回启发式。"""
    gateway = context.gateway
    if gateway is None or not getattr(gateway, "client", None):
        return []
    policy = normalized_policy(snapshot.get("extraction_policy"))
    windows = _text_windows(context, policy["chunk_size"], policy["chunk_overlap"] if snapshot.get("chunk_policy") == "fixed_token" else 0)
    if not windows:
        return []
    role_spec = _role_spec(snapshot)
    prompt = _load_prompt().replace("{{roles}}", role_spec["prompt_block"]).replace("{{chunk_size}}", str(policy["chunk_size"]))
    allowed_keys = role_spec["allowed_keys"]
    native_roles = role_spec["native_roles"]
    custom_keys = role_spec["custom_keys"]
    drafts: list[KnowledgeUnitDraft] = []
    failed = 0
    for window in windows:
        result = gateway.chat_json(
            prompt,
            json.dumps(
                {
                    "section_id": window.get("section_id") or "",
                    "section_title": window.get("title") or "",
                    "page": window.get("page") or 1,
                    "text": window["text"],
                },
                ensure_ascii=False,
            ),
            temperature=0.0,
        )
        items = result.get("units") if isinstance(result, dict) else None
        if not items:
            failed += 1
            continue
        for item in items:
            draft = _unit_from_item(item, window, context, knowledge_type, allowed_keys, native_roles, custom_keys)
            if draft:
                drafts.append(draft)
    pipeline_step(
        "ingest",
        "role_llm_extract",
        inputs={
            "filename": context.filename,
            "windows": len(windows),
            "roles": sorted(allowed_keys),
            "chunk_size": policy["chunk_size"],
        },
        result={**draft_digest(drafts), "failed_windows": failed, "ok": bool(drafts)},
    )
    return drafts


def _load_prompt() -> str:
    return load_prompt(PROMPT_ID, DEFAULT_PROMPT)


def _role_spec(snapshot: dict) -> dict:
    """把快照 Role（含中文 label 与自定义关键词）编进 Prompt，并区分原生/自定义。"""
    keys = [str(key) for key in (snapshot.get("roles") or []) if str(key).strip()]
    keys = [key for key in keys if key not in {"formula", "reference"}]
    rules = {str(rule.get("key")): rule for rule in snapshot.get("role_rules") or [] if rule.get("key")}
    native_roles = {SemanticRole(key) for key in keys if key in {role.value for role in SemanticRole}}
    custom_keys = {key for key in keys if key not in {role.value for role in SemanticRole}}
    lines: list[str] = []
    for key in keys:
        rule = rules.get(key) or {}
        label = rule.get("label") or ROLE_LABELS.get(key) or key
        keywords = [str(word) for word in (rule.get("keywords") or []) if str(word).strip()]
        kind = "自定义" if key in custom_keys else "内置"
        extra = f" 关键词: {', '.join(keywords)}" if keywords else ""
        lines.append(f"- {key}（{label}，{kind}）{extra}")
    return {
        "allowed_keys": set(keys),
        "native_roles": native_roles or {SemanticRole.EXPLANATION},
        "custom_keys": custom_keys,
        "prompt_block": "\n".join(lines) if lines else "- explanation（解释说明，内置）",
    }


def _text_windows(context: DocumentContext, chunk_size: int, overlap: int = 0) -> list[dict]:
    """优先按章节切窗口，否则按页；再按策略 chunk_size 限制上下文，避免一次塞整篇。"""
    records: list[dict] = []
    sections = [
        section
        for section in (context.structure or {}).get("sections") or []
        if not _skip_section(section)
    ]
    if sections:
        for section in sections:
            text = (section.get("text") or "").strip()
            if not text:
                continue
            records.append(
                {
                    "section_id": section.get("id") or "",
                    "title": section.get("title") or section.get("id") or context.filename,
                    "page": int(section.get("page") or 1),
                    "text": text,
                    "anchor": f"sec:{section.get('id')}" if section.get("id") else "",
                }
            )
    else:
        pages = (context.structure or {}).get("pages") or [{"page": 1, "text": context.text}]
        for page in pages:
            text = (page.get("text") or "").strip()
            if not text:
                continue
            records.append(
                {
                    "section_id": "",
                    "title": context.filename,
                    "page": int(page.get("page") or 1),
                    "text": text,
                    "anchor": f"text:p{page.get('page', 1)}",
                }
            )
    windows: list[dict] = []
    for record in records:
        parts = split_content(record["text"], chunk_size, overlap)
        for index, part in enumerate(parts):
            if len(part) < 20:
                continue
            windows.append(
                {
                    **record,
                    "text": part,
                    "part": index + 1,
                    "parts": len(parts),
                    "anchor": f"{record['anchor']}:w{index + 1}" if record["anchor"] else f"win:{len(windows)}",
                }
            )
    return windows


def _skip_section(section: dict) -> bool:
    token = f"{section.get('id') or ''} {section.get('title') or ''}".lower()
    return any(token.startswith(prefix) or f" {prefix}" in token for prefix in SKIP_SECTION_PREFIXES)


def _unit_from_item(
    item: dict,
    window: dict,
    context: DocumentContext,
    knowledge_type: KnowledgeType,
    allowed_keys: set[str],
    native_roles: set[SemanticRole],
    custom_keys: set[str],
) -> KnowledgeUnitDraft | None:
    content = str(item.get("content") or "").strip()
    if len(content) < 12:
        return None
    role_key = str(item.get("semantic_role") or "").strip()
    if role_key not in allowed_keys:
        return None
    if role_key in {"formula", "reference"}:
        return None
    custom: list[str] = []
    if role_key in custom_keys:
        native = SemanticRole.EXPLANATION if SemanticRole.EXPLANATION in native_roles else next(iter(native_roles))
        custom = [role_key]
    else:
        try:
            native = SemanticRole(role_key)
        except ValueError:
            return None
        if native not in native_roles:
            return None
    extra_custom = [str(key) for key in (item.get("custom_roles") or []) if str(key) in custom_keys]
    custom = list(dict.fromkeys(custom + extra_custom))
    span = _ground_span(window["text"], content, str(item.get("source_span") or ""))
    title = str(item.get("title") or window.get("title") or native.value)[:180]
    parent_anchor = window.get("anchor") or ""
    meta = {
        "kind": "concept",
        "extraction_source": "role_llm",
        "section_id": window.get("section_id") or "",
        "parent_anchor": parent_anchor,
        **(item.get("unit_meta") or {}),
    }
    if custom:
        meta["custom_roles"] = custom
    return KnowledgeUnitDraft(
        title=title,
        content=content,
        semantic_role=native,
        knowledge_type=knowledge_type,
        importance=str(item.get("importance") or "core"),
        concepts=list(item.get("concepts") or _extract_concepts(content))[:8],
        source_span=span,
        source_chapter=str(window.get("section_id") or ""),
        source_section=str(window.get("title") or "")[:80],
        source_page=int(window.get("page") or 1),
        parent_context=f"{context.filename} / {window.get('title')}",
        confidence=0.82,
        relations=[{"type": "BELONGS_TO", "to_key": parent_anchor}] if parent_anchor else [],
        unit_meta=meta,
    )


def _ground_span(window: str, content: str, claimed: str) -> str:
    """source_span 必须落在当前窗口原文里，避免模型另写一句无法对照。"""
    claimed = claimed.strip()
    if claimed and claimed in window:
        return claimed[:500]
    if content and content in window:
        return content[:500]
    return window[:500]
