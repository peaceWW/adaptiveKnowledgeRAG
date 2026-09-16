"""架构类问答的证据排序：图 → 公式 → 表 → 说明，供检索扩展、完整度与生成共用。"""
from __future__ import annotations

from typing import Any

# 架构/电路问法：需要框图才能建立结构；不含这些词的 CDC/指标问答不得因缺图判失败
ARCHITECTURE_MARKERS = (
    "架构",
    "框图",
    "电路",
    "接收机",
    "receiver",
    "architecture",
    "hybrid",
    "混合接收",
)
KIND_WEIGHTS_ARCH = {"figure": 3.0, "equation": 2.0, "table": 1.5, "text": 1.0}
# 非架构问题仍图优先，但权重差缩小，避免指标问答被无关框图抢走
KIND_WEIGHTS_DEFAULT = {"figure": 1.4, "equation": 1.3, "table": 1.1, "text": 1.0}
KIND_LABELS = {"figure": "【图】", "equation": "【公式】", "table": "【表】"}
KIND_CAP = {"figure": 3, "equation": 4, "table": 2, "text": 6}
KIND_TOKENS = {"figure", "equation", "table", "text"}
SIBLING_EXPAND_CAP = 8
# 公式/抽头问法：先公式后图，避免被架构框图抢走
FORMULA_MARKERS = (
    "系数",
    "抽头",
    "公式",
    "eq.",
    "equation",
    "latex",
    "tap",
    "coefficient",
)


def is_architecture_query(query: str) -> bool:
    """是否应按「先图后公式」补全与加权。ADC 单独出现不算，须与架构类词同现。"""
    text = (query or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in text or marker in lowered for marker in ARCHITECTURE_MARKERS):
        return True
    # 「ADC 架构/电路」才升格；纯 ENOB/功耗不问框图
    if "adc" in lowered and any(token in lowered or token in text for token in ("架构", "框图", "电路", "receiver", "architecture", "hybrid")):
        return True
    return False


def is_formula_query(query: str) -> bool:
    """抽头/系数/公式问法：优先公式，而不是先出摘要或框图。"""
    text = (query or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if is_architecture_query(text):
        return False
    return any(marker in text or marker in lowered for marker in FORMULA_MARKERS)


def infer_evidence_types(query: str, intent: str = "") -> list[str]:
    """understand 未返回 evidence_types 时的启发式：架构图优先，系数/公式则公式优先。"""
    if is_architecture_query(query):
        return ["figure", "equation", "text"]
    if is_formula_query(query):
        return ["equation", "figure", "text"]
    if str(intent or "").lower() in {"comparison"}:
        return ["text", "table", "figure"]
    return ["text", "equation", "figure"]


def normalize_kind(hit: dict[str, Any] | None) -> str:
    """把 unit_meta.kind / 截图字段 / formula 角色归一成 figure|equation|table|text。"""
    item = hit or {}
    kind = str(item.get("kind") or "").lower()
    if kind in {"figure", "equation", "table"}:
        return kind
    if item.get("image_key") or item.get("image_url"):
        return "figure"
    role = str(item.get("semantic_role") or item.get("role") or "").lower()
    if role in {"formula", "equation"} or kind == "formula":
        return "equation"
    if kind in {"concept", "section", "metadata", "parameter", "citation", "text", ""}:
        return "text"
    return "text"


def evidence_priority(query: str, intent: str = "", evidence_types: list[str] | None = None) -> dict[str, float]:
    """按 evidence_types 顺序赋权；架构问图最重，系数/公式问公式最重。"""
    ordered = [item for item in (evidence_types or []) if item in KIND_WEIGHTS_ARCH]
    if not ordered:
        if is_formula_query(query):
            return {"figure": 2.0, "equation": 3.0, "table": 1.5, "text": 1.0}
        if is_architecture_query(query) or str(intent or "").lower() in {"definition"}:
            return dict(KIND_WEIGHTS_ARCH)
        return dict(KIND_WEIGHTS_DEFAULT)
    weights = dict(KIND_WEIGHTS_DEFAULT)
    for index, kind in enumerate(ordered):
        weights[kind] = max(3.0 - index * 0.8, 1.0)
    if "text" not in ordered:
        weights["text"] = 1.0
    return weights


def evidence_label(kind: str) -> str:
    """写入 LLM context 的块标签，强制生成侧按图/公式/说明阅读。"""
    return KIND_LABELS.get(kind, "【说明】")


def order_context_hits(
    hits: list[dict[str, Any]],
    query: str = "",
    intent: str = "",
    evidence_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """同一证据包内按 kind 权重再按分数排；核心命中与 relation/sibling 邻居共用此序。"""
    weights = evidence_priority(query, intent, evidence_types)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits or []:
        hid = str(hit.get("id") or "")
        if hid and hid in seen:
            continue
        if hid:
            seen.add(hid)
        unique.append(hit)

    def sort_key(hit: dict[str, Any]) -> tuple[float, float]:
        kind = normalize_kind(hit)
        weight = weights.get(kind, 1.0)
        score = float(hit.get("score") or 0)
        return (-weight, -score)

    unique.sort(key=sort_key)
    return unique


def cap_evidence_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """生成前按 kind 限额，避免上下文被长说明挤掉图和公式。"""
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in KIND_CAP}
    for hit in hits or []:
        kind = normalize_kind(hit)
        if len(buckets[kind]) < KIND_CAP[kind]:
            buckets[kind].append(hit)
    return buckets["figure"] + buckets["equation"] + buckets["table"] + buckets["text"]


def split_missing_roles_and_kinds(missing: list[str]) -> tuple[list[str], list[str]]:
    """二次检索：figure 走 Qdrant extra_filters.kind，其它仍当 semantic_role。"""
    roles: list[str] = []
    kinds: list[str] = []
    for item in missing or []:
        token = str(item or "").strip().lower()
        if token in KIND_TOKENS:
            kinds.append(token)
        elif token:
            roles.append(item)
    return roles, kinds


def adjust_figure_completeness(
    query: str,
    hits: list[dict[str, Any]],
    missing: list[str],
    need_secondary: bool,
    secondary_query: str,
) -> tuple[list[str], bool, str]:
    """架构问无 figure 则补 missing=figure；非架构问去掉 figure 缺口，避免 markdown 被判不完整。"""
    missing_list = [str(item) for item in (missing or []) if str(item).strip()]
    has_figure = any(normalize_kind(hit) == "figure" for hit in hits or [])
    if is_architecture_query(query):
        if not has_figure:
            if "figure" not in missing_list:
                missing_list.append("figure")
            chapters = " ".join(
                dict.fromkeys(
                    str(hit.get("source_chapter") or "").strip()
                    for hit in hits or []
                    if str(hit.get("source_chapter") or "").strip()
                )
            )
            query_text = (secondary_query or "").strip() or query
            extra = " ".join(part for part in ("Fig", "architecture", chapters) if part)
            return missing_list, True, f"{query_text} {extra}".strip()
        return missing_list, need_secondary, secondary_query
    missing_list = [item for item in missing_list if item.lower() != "figure"]
    if not missing_list:
        return missing_list, False, secondary_query
    return missing_list, need_secondary, secondary_query


def adjust_kind_completeness(
    query: str,
    hits: list[dict[str, Any]],
    missing: list[str],
    need_secondary: bool,
    secondary_query: str,
    required_kinds: list[str] | None = None,
) -> tuple[list[str], bool, str]:
    """架构问按 required kinds 要 figure；公式问要 equation。角色完整度不够时不再只查 definition。"""
    missing_list, need, query_text = adjust_figure_completeness(
        query, hits, missing, need_secondary, secondary_query
    )
    kinds_needed = [str(item).lower() for item in (required_kinds or []) if str(item).lower() in KIND_TOKENS]
    has_equation = any(normalize_kind(hit) == "equation" for hit in hits or [])
    if is_formula_query(query) or "equation" in kinds_needed:
        if is_formula_query(query) and not has_equation:
            if "equation" not in missing_list:
                missing_list.append("equation")
            extra = " ".join(part for part in ((query_text or query).strip(), "Eq", "formula") if part)
            return missing_list, True, extra.strip()
    if not is_formula_query(query):
        missing_list = [item for item in missing_list if item.lower() != "equation"]
        if not missing_list:
            return missing_list, False, query_text
    return missing_list, need, query_text
