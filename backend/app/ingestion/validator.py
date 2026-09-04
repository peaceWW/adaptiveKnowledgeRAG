from __future__ import annotations

from app.domain.enums import HIGH_RISK_ROLES, KnowledgeLifecycle, SemanticRole
from app.domain.strategy import KnowledgeUnitDraft


def validate_draft(draft: KnowledgeUnitDraft) -> tuple[KnowledgeLifecycle, bool]:
    """Return lifecycle and whether a human review task is required."""
    if not draft.content.strip() or not draft.source_span.strip():
        return KnowledgeLifecycle.DRAFT, True
    if draft.semantic_role in HIGH_RISK_ROLES:
        return KnowledgeLifecycle.PENDING_REVIEW, True
    if draft.semantic_role in {SemanticRole.EXAMPLE, SemanticRole.EXPLANATION, SemanticRole.REFERENCE}:
        return KnowledgeLifecycle.PUBLISHED, False
    return KnowledgeLifecycle.AI_PROCESSED, False
