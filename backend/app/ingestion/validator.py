from __future__ import annotations

from app.domain.enums import HIGH_RISK_ROLES, KnowledgeLifecycle, SemanticRole
from app.domain.strategy import KnowledgeUnitDraft


def validate_draft(draft: KnowledgeUnitDraft) -> tuple[KnowledgeLifecycle, bool]:
    """决定入库生命周期：空内容保持 DRAFT；高风险进审核；其余 AI_PROCESSED 即可被问答检索。"""
    if not draft.content.strip() or not draft.source_span.strip():
        return KnowledgeLifecycle.DRAFT, True
    if draft.semantic_role in HIGH_RISK_ROLES:
        return KnowledgeLifecycle.PENDING_REVIEW, True
    if draft.semantic_role in {SemanticRole.EXAMPLE, SemanticRole.EXPLANATION, SemanticRole.REFERENCE}:
        return KnowledgeLifecycle.PUBLISHED, False
    return KnowledgeLifecycle.AI_PROCESSED, False
