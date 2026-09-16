from __future__ import annotations

import re
from typing import Iterable

from app.domain.enums import KnowledgeType, SemanticRole
from app.domain.strategy import DocumentContext, KnowledgeUnitDraft
from app.observability.pipeline_log import draft_digest, step as pipeline_step

ROLE_HINTS: list[tuple[SemanticRole, tuple[str, ...]]] = [
    (SemanticRole.DEFINITION, ("定义", "definition", "是指", "refers to", "什么是")),
    (SemanticRole.PRINCIPLE, ("原理", "principle", "mechanism", "机制", "architecture", "why")),
    (SemanticRole.FORMULA, ("公式", "formula", "equation", "mtbf", "tsu", "th", "snr =", "enob")),
    (SemanticRole.METRIC, ("sndr", "enob", "ber", "gb/s", "mw", "fom", "measurement", "measured")),
    (SemanticRole.PARAMETER, ("parameter", "resolution", "sampling", "tap", "nm cmos", "supply")),
    (SemanticRole.COMPARISON, ("compared with", "comparison", "versus", "relative to prior")),
    (SemanticRole.LIMITATION, ("limitation", "drawback", "however", "at the cost")),
    (SemanticRole.INTERFACE, ("interface", "block diagram", "front-end", "clock path")),
    (SemanticRole.SUMMARY, ("abstract", "in this paper", "this work", "conclusion")),
    (SemanticRole.BACKGROUND, ("introduction", "previous work", "prior art")),
    (SemanticRole.REFERENCE, ("references", "et al", "[1]", "ieee jssc")),
    (SemanticRole.CONSTRAINT, ("约束", "constraint", "must", "shall", "禁止", "必须")),
    (SemanticRole.RULE, ("规则", "rule", "design rule")),
    (SemanticRole.EXAMPLE, ("例如", "example", "示例", "for example")),
    (SemanticRole.EXCEPTION, ("例外", "exception", "unless", "不适用于")),
    (SemanticRole.SOLUTION, ("解决", "solution", "推荐使用", "workaround", "同步器", "fifo")),
    (SemanticRole.ROOT_CAUSE, ("原因", "root cause", "caused by", "亚稳态")),
    (SemanticRole.SYMPTOM, ("现象", "symptom", "failure")),
    (SemanticRole.PREVENTION, ("预防", "prevention", "best practice")),
    (SemanticRole.API_INPUT, ("input", "request", "参数", "parameter")),
    (SemanticRole.API_OUTPUT, ("output", "response", "返回")),
    (SemanticRole.ERROR_CODE, ("error", "异常", "status code")),
    (SemanticRole.EXPLANATION, ("说明", "explanation", "note")),
    (SemanticRole.REQUIREMENT, ("需求", "requirement", "应当")),
    (SemanticRole.PROCEDURE, ("流程", "procedure", "步骤如下")),
    (SemanticRole.WARNING, ("警告", "注意", "warning")),
    (SemanticRole.OBLIGATION, ("义务", "obligation")),
    (SemanticRole.PROHIBITION, ("不得", "prohibition")),
    (SemanticRole.BEST_PRACTICE, ("最佳实践", "best practice")),
]


def extract_units_from_text(
    context: DocumentContext,
    allowed_roles: Iterable[SemanticRole],
    knowledge_type: KnowledgeType,
) -> list[KnowledgeUnitDraft]:
    allowed = set(allowed_roles)
    chapters = context.structure.get("chapters") or []
    pages = context.structure.get("pages") or [{"page": 1, "text": context.text}]
    drafts: list[KnowledgeUnitDraft] = []
    parent_stack: list[str] = [context.filename]
    split_rules: list[str] = []

    for page in pages:
        page_no = int(page.get("page") or 1)
        blocks, rule = _split_blocks(page.get("text") or "")
        split_rules.append(rule)
        for block in blocks:
            heading = _first_line(block)
            role = _infer_role(block, allowed)
            if role not in allowed:
                role = next(iter(allowed), SemanticRole.DEFINITION)
            if _looks_like_heading(heading):
                parent_stack = parent_stack[:1] + [heading]
            concepts = _extract_concepts(block)
            drafts.append(
                KnowledgeUnitDraft(
                    title=heading[:180] or concepts[0] if concepts else f"{role.value}-{page_no}",
                    content=block.strip(),
                    semantic_role=role,
                    knowledge_type=knowledge_type,
                    importance="core" if role in {
                        SemanticRole.DEFINITION,
                        SemanticRole.CONSTRAINT,
                        SemanticRole.RULE,
                        SemanticRole.SOLUTION,
                    } else "supporting",
                    concepts=concepts,
                    source_span=block[:500],
                    source_chapter=_match_chapter(chapters, page_no),
                    source_section=heading[:80],
                    source_page=page_no,
                    parent_context=" / ".join(parent_stack[-3:]),
                    confidence=0.78 if role != SemanticRole.EXPLANATION else 0.7,
                )
            )
    if not drafts:
        drafts = [
            KnowledgeUnitDraft(
                title=context.filename,
                content=context.text[:2000],
                semantic_role=SemanticRole.DEFINITION,
                knowledge_type=knowledge_type,
                source_span=context.text[:500],
                parent_context=context.filename,
            )
        ]
        split_rules.append("whole_document_fallback")
    pipeline_step(
        "ingest",
        "chunk",
        inputs={
            "filename": context.filename,
            "knowledge_type": knowledge_type.value,
            "pages": len(pages),
            "text_len": len(context.text or ""),
        },
        result={
            "rule": _dominant_split_rule(split_rules),
            "page_rules": split_rules[:8],
            **draft_digest(drafts),
        },
    )
    return drafts


def _split_blocks(text: str) -> tuple[list[str], str]:
    """先按空行切块；没有合格段落时再按句攒到约 180 字。返回 (块, 规则名)。"""
    parts = re.split(r"\n\s*\n+", text)
    blocks = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1 and blocks:
        return blocks, "blank_line"
    sentences = re.split(r"(?<=[。.!?\n])", text)
    chunk: list[str] = []
    buf = ""
    for sent in sentences:
        buf += sent
        if len(buf) > 180:
            chunk.append(buf.strip())
            buf = ""
    if buf.strip():
        chunk.append(buf.strip())
    return chunk, "sentence_~180"


def _dominant_split_rule(rules: list[str]) -> str:
    if not rules:
        return "none"
    if all(rule == rules[0] for rule in rules):
        return rules[0]
    return "mixed:" + ",".join(sorted(set(rules)))


def _infer_role(text: str, allowed: set[SemanticRole]) -> SemanticRole:
    lowered = text.lower()
    for role, hints in ROLE_HINTS:
        if role not in allowed:
            continue
        if any(hint in lowered for hint in hints):
            return role
    if SemanticRole.DEFINITION in allowed:
        return SemanticRole.DEFINITION
    return next(iter(allowed))


def _extract_concepts(text: str) -> list[str]:
    patterns = [
        r"\b(CDC|MTBF|FIFO|RTL|FSM|ATPG|MBIST|PCIe|DDR\d|Setup Time|Hold Time|Metastability|Synchronizer|Gray Code)\b",
        r"\b(ADC|SAR|TI-ADC|FFE|DFE|CTLE|CDR|ENOB|SNDR|SFDR|FoM|BER|NRZ|PAM-4|SerDes|AFE)\b",
        r"\b(time[- ]interleaving|embedded equalization|hybrid ADC|decision feedback|feed-forward)\b",
        r"(亚稳态|同步器|建立时间|保持时间|跨时钟域|均衡器|模数转换)",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    unique: list[str] = []
    for item in found:
        value = item if isinstance(item, str) else item[0]
        if value not in unique:
            unique.append(value)
    return unique[:8]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _looks_like_heading(line: str) -> bool:
    return bool(line) and len(line) < 80 and not line.endswith("。")


def _match_chapter(chapters: list[dict], page: int) -> str:
    for chapter in reversed(chapters):
        if int(chapter.get("page") or 1) <= page:
            return str(chapter.get("title") or "")
    return ""
