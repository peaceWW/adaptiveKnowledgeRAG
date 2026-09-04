from __future__ import annotations

import re
from typing import Iterable

from app.domain.enums import KnowledgeType, SemanticRole
from app.domain.strategy import DocumentContext, KnowledgeUnitDraft

ROLE_HINTS: list[tuple[SemanticRole, tuple[str, ...]]] = [
    (SemanticRole.DEFINITION, ("定义", "definition", "是指", "refers to", "什么是")),
    (SemanticRole.PRINCIPLE, ("原理", "principle", "mechanism", "机制", "why")),
    (SemanticRole.FORMULA, ("公式", "formula", "mtbf", "tsu", "th")),
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

    for page in pages:
        page_no = int(page.get("page") or 1)
        blocks = _split_blocks(page.get("text") or "")
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
    return drafts or [
        KnowledgeUnitDraft(
            title=context.filename,
            content=context.text[:2000],
            semantic_role=SemanticRole.DEFINITION,
            knowledge_type=knowledge_type,
            source_span=context.text[:500],
            parent_context=context.filename,
        )
    ]


def _split_blocks(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", text)
    blocks = [p.strip() for p in parts if len(p.strip()) > 40]
    if blocks:
        return blocks
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
    return chunk


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
        r"(亚稳态|同步器|建立时间|保持时间|跨时钟域)",
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
