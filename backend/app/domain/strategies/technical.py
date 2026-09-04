from __future__ import annotations

from typing import Any

from app.domain.enums import INTENT_ROLE_MAP, KnowledgeType, QueryIntent, SemanticRole
from app.domain.strategy import (
    CompletenessResult,
    DocumentContext,
    KnowledgeUnitDraft,
    QueryContext,
    RetrievalPlan,
)
from app.ingestion.extractor import extract_units_from_text


class TechnicalKnowledgeStrategy:
    ROLES = [
        SemanticRole.DEFINITION,
        SemanticRole.EXPLANATION,
        SemanticRole.PRINCIPLE,
        SemanticRole.FORMULA,
        SemanticRole.PARAMETER,
        SemanticRole.CONSTRAINT,
        SemanticRole.RULE,
        SemanticRole.EXAMPLE,
        SemanticRole.EXCEPTION,
        SemanticRole.REFERENCE,
    ]

    def type(self) -> KnowledgeType:
        return KnowledgeType.TECHNICAL_CONCEPT

    def ontology(self) -> dict[str, Any]:
        return {
            "name": "Technical Knowledge V1",
            "roles": [role.value for role in self.ROLES],
            "structure": "TechnicalConcept → Definition/Principle/Formula/Constraint/Example/Exception",
        }

    def build_units(self, context: DocumentContext) -> list[KnowledgeUnitDraft]:
        return extract_units_from_text(
            context,
            allowed_roles=self.ROLES,
            knowledge_type=KnowledgeType.TECHNICAL_CONCEPT,
        )

    def plan(self, query: QueryContext) -> RetrievalPlan:
        roles = INTENT_ROLE_MAP.get(query.intent, [SemanticRole.DEFINITION, SemanticRole.EXPLANATION])
        graph = query.intent in {QueryIntent.SOLUTION, QueryIntent.CAUSE, QueryIntent.RISK}
        return RetrievalPlan(
            intent=query.intent,
            topics=query.topics,
            required_roles=roles,
            graph_expand=graph,
            search_strategy="HYBRID",
            completeness_check=True,
            steps=[
                {"type": "catalog_filter", "domain": query.domain},
                {"type": "concept_search", "concepts": query.topics},
                {"type": "hybrid_search", "roles": [r.value for r in roles]},
                {"type": "completeness_check"},
            ],
        )

    def check_completeness(
        self, query: QueryContext, retrieved_roles: list[str], retrieved_titles: list[str]
    ) -> CompletenessResult:
        required = [r.value for r in INTENT_ROLE_MAP.get(query.intent, [SemanticRole.DEFINITION])]
        covered = [role for role in required if role in retrieved_roles]
        missing = [role for role in required if role not in covered]
        score = len(covered) / max(len(required), 1)
        return CompletenessResult(
            required_knowledge=required,
            covered=covered,
            missing=missing,
            completeness_score=round(score, 2),
            need_secondary_retrieval=score < 0.8,
            secondary_query=" ".join(query.topics + missing),
        )
