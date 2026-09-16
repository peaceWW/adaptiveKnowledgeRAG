"""图/公式捆绑：工程主题、互指关系、章节 Fig/Eq 概念。抽取与旧数据回填共用。"""
from __future__ import annotations

import re
from typing import Any, Iterable

FIG_REF_RE = re.compile(r"\bFig(?:ure)?\.?\s*(\d+[A-Za-z]?)\b", re.I)
EQ_REF_RE = re.compile(r"\bEq(?:uation)?\.?\s*\(?\s*(\d{1,3})", re.I)
# 图注里的 Eq.(3) / (3) 仅在编号确实存在时才当公式引用
BARE_EQ_RE = re.compile(r"\((\d{1,2})\)")

# 可见模块/图注 → 稳定 slug，写入 embedding，方便「混合接收机」命中 Fig.4
TOPIC_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("hybrid", "adc", "receiver"), "hybrid_adc_receiver"),
    (("hybrid", "receiver"), "hybrid_adc_receiver"),
    (("混合", "接收"), "hybrid_adc_receiver"),
    (("embedded", "ffe"), "embedded_ffe"),
    (("3-tap", "ffe"), "embedded_ffe"),
    (("三抽头",), "embedded_ffe"),
    (("analog", "ffe"), "analog_ffe"),
    (("digital", "ffe"), "digital_ffe"),
    (("feed-forward",), "ffe"),
    (("dfe",), "dfe"),
    (("ctle",), "ctle"),
    (("sar", "adc"), "sar_adc"),
    (("ti-adc",), "ti_adc"),
    (("time-interleaved",), "ti_adc"),
    (("cdr",), "cdr"),
    (("pll",), "pll"),
)


def infer_engineering_topic(*parts: Any, suggested: str = "") -> str:
    """从 caption/组件/论文题推断 engineering_topic；优先用 Vision 给出的合法 slug。"""
    slug = _slug(suggested)
    if slug:
        return slug
    blob = _norm(" ".join(str(part or "") for part in parts))
    for tokens, topic in TOPIC_RULES:
        if all(token in blob for token in tokens):
            return topic
    if "architecture" in blob or "框图" in blob or "block diagram" in blob:
        return "architecture_block"
    if "circuit" in blob or "电路" in blob:
        return "circuit"
    return ""


def figure_content(
    fig_id: str,
    caption: str,
    *,
    figure_type: str = "",
    components: Iterable[Any] | None = None,
    parameters: dict[str, Any] | None = None,
    description: str = "",
    engineering_topic: str = "",
) -> str:
    """图单元正文：title/caption/components/topic 都进 embedding 源文本。"""
    comps = [str(item).strip() for item in (components or []) if str(item).strip()]
    parts = [f"Fig. {fig_id}. {caption}".strip()]
    if engineering_topic:
        parts.append(f"Topic: {engineering_topic}")
    if figure_type:
        parts.append(f"Type: {figure_type}")
    if comps:
        parts.append("Components: " + ", ".join(comps))
    if parameters:
        parts.append("Parameters: " + ", ".join(f"{key}={value}" for key, value in parameters.items()))
    if description:
        parts.append(f"Description: {description}")
    return "\n".join(parts)


def equation_content(
    eq_id: str,
    *,
    latex: str = "",
    raw: str = "",
    nearby: str = "",
    meaning: str = "",
    variables: dict[str, Any] | None = None,
) -> str:
    """公式单元正文，供向量前缀「公式:」区分普通段落。"""
    parts = [f"Equation ({eq_id})"]
    if latex:
        parts.append(f"$$\n{latex}\n$$")
    if raw:
        parts.append(f"Source: {raw}")
    if nearby:
        parts.append(f"Context: {nearby}")
    if meaning:
        parts.append(f"Meaning: {meaning}")
    if variables:
        parts.append("Symbols: " + ", ".join(f"{key}={value}" for key, value in variables.items()))
    return "\n".join(parts)


def fig_eq_concepts(text: str, structure: dict[str, Any] | None = None, section_anchor: str = "") -> list[str]:
    """章节说明必须带上该节出现的 Fig/Eq 编号，便于只问模块名也能关键词命中。"""
    refs: list[str] = []
    for num in FIG_REF_RE.findall(text or ""):
        refs.append(f"Fig.{num}")
    for num in EQ_REF_RE.findall(text or ""):
        refs.append(f"Eq.({num})")
    structure = structure or {}
    for fig in structure.get("figures") or []:
        fig_id = str(fig.get("fig_id") or "")
        parent = str(fig.get("parent_anchor") or "")
        caption = str(fig.get("caption") or "")
        if fig_id and (section_anchor and (parent == section_anchor or f"Fig.{fig_id}" in refs or section_anchor in caption)):
            refs.append(f"Fig.{fig_id}")
        elif fig_id and section_anchor and f"Fig. {fig_id}" in (text or ""):
            refs.append(f"Fig.{fig_id}")
    for eq in structure.get("equations") or []:
        eq_id = str(eq.get("eq_id") or "")
        if eq_id and (f"Eq.({eq_id})" in refs or (text and f"({eq_id})" in text)):
            refs.append(f"Eq.({eq_id})")
    return _unique(refs)


def merge_concepts(*groups: Iterable[Any], limit: int = 12) -> list[str]:
    """领域词在前、Fig/Eq 编号随后，避免把 Fig.1 当成图谱专题名。"""
    domain: list[str] = []
    anchors: list[str] = []
    for group in groups:
        for item in group or []:
            value = str(item).strip()
            if not value:
                continue
            target = anchors if _is_fig_eq_concept(value) else domain
            if value not in target:
                target.append(value)
    return (domain + anchors)[:limit]


def figure_equation_pairs(figures: list[dict[str, Any]], equations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """同页或 caption/nearby 互指 Fig.N / Eq.N 时成对，供 HAS_EQUATION / HAS_FIGURE。"""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    eq_ids = {str(eq.get("eq_id") or "") for eq in equations if eq.get("eq_id")}
    for fig in figures:
        fig_id = str(fig.get("fig_id") or "")
        if not fig_id:
            continue
        fig_blob = " ".join(str(fig.get(key) or "") for key in ("caption", "content", "description"))
        mentioned_eq = set(EQ_REF_RE.findall(fig_blob))
        mentioned_eq.update(num for num in BARE_EQ_RE.findall(fig_blob) if num in eq_ids)
        fig_page = int(fig.get("page") or fig.get("source_page") or 0)
        for eq in equations:
            eq_id = str(eq.get("eq_id") or "")
            if not eq_id:
                continue
            eq_blob = " ".join(str(eq.get(key) or "") for key in ("nearby_text", "raw", "content", "meaning"))
            eq_page = int(eq.get("page") or eq.get("source_page") or 0)
            same_page = bool(fig_page and eq_page and fig_page == eq_page)
            caption_ref = eq_id in mentioned_eq or fig_id in FIG_REF_RE.findall(eq_blob)
            if not (same_page or caption_ref):
                continue
            key = (fig_id, eq_id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
    return pairs


def _is_fig_eq_concept(value: str) -> bool:
    text = str(value or "")
    return bool(FIG_REF_RE.search(text) or EQ_REF_RE.search(text) or re.match(r"Eq\.\(", text))


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not text or text in {"other", "figure", "plot", "unknown"}:
        return ""
    return text[:64]


def _norm(text: str) -> str:
    return re.sub(r"[\s_‐‑–—-]+", " ", str(text or "")).casefold()


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
