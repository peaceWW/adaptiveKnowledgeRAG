from __future__ import annotations

from typing import Any

from app.domain.enums import KnowledgeType, QueryIntent, SemanticRole
from app.domain.strategy import (
    CompletenessResult,
    DocumentContext,
    KnowledgeUnitDraft,
    QueryContext,
    RetrievalPlan,
)
from app.ingestion.extractor import extract_units_from_text


class IncidentCaseStrategy:
    ROLES = [
        SemanticRole.ENVIRONMENT,
        SemanticRole.SYMPTOM,
        SemanticRole.IMPACT,
        SemanticRole.ROOT_CAUSE,
        SemanticRole.SOLUTION,
        SemanticRole.PREVENTION,
        SemanticRole.DEFINITION,
    ]

    def type(self) -> KnowledgeType:
        return KnowledgeType.INCIDENT_CASE

    def ontology(self) -> dict[str, Any]:
        return {
            "name": "Incident Case V1",
            "roles": [role.value for role in self.ROLES],
        }

    def build_units(self, context: DocumentContext) -> list[KnowledgeUnitDraft]:
        return extract_units_from_text(
            context,
            allowed_roles=self.ROLES,
            knowledge_type=KnowledgeType.INCIDENT_CASE,
        )

    def plan(self, query: QueryContext) -> RetrievalPlan:
        if query.intent == QueryIntent.SOLUTION:
            roles = [SemanticRole.SYMPTOM, SemanticRole.ROOT_CAUSE, SemanticRole.SOLUTION, SemanticRole.PREVENTION]
        elif query.intent == QueryIntent.CAUSE:
            roles = [SemanticRole.ENVIRONMENT, SemanticRole.SYMPTOM, SemanticRole.ROOT_CAUSE]
        else:
            roles = self.ROLES
        return RetrievalPlan(
            intent=query.intent,
            topics=query.topics,
            required_roles=roles,
            graph_expand=True,
            search_strategy="HYBRID",
            completeness_check=True,
            steps=[
                {"type": "metadata_filter", "knowledge_type": self.type().value},
                {"type": "hybrid_search", "roles": [r.value for r in roles]},
            ],
        )

    def check_completeness(
        self, query: QueryContext, retrieved_roles: list[str], retrieved_titles: list[str]
    ) -> CompletenessResult:
        required = [r.value for r in self.plan(query).required_roles]
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
