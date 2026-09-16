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
from app.ingestion.paper_extractor import extract_paper_units
from app.observability.pipeline_log import step as pipeline_step
from app.retrieval.evidence_order import infer_evidence_types, is_architecture_query


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
        SemanticRole.METRIC,
        SemanticRole.COMPARISON,
        SemanticRole.LIMITATION,
        SemanticRole.INTERFACE,
        SemanticRole.SUMMARY,
        SemanticRole.BACKGROUND,
    ]

    def type(self) -> KnowledgeType:
        return KnowledgeType.TECHNICAL_CONCEPT

    def ontology(self) -> dict[str, Any]:
        return {
            "name": "Technical Knowledge V1",
            "roles": [role.value for role in self.ROLES],
            "structure": "TechnicalConcept → Definition/Principle/Formula/Constraint/Metric/Reference",
            "document_genres": ["generic", "academic_paper"],
        }

    def build_units(self, context: DocumentContext) -> list[KnowledgeUnitDraft]:
        academic, reason = _academic_paper_decision(context)
        process_config = (context.structure or {}).get("process_config") or {}
        pipeline_step(
            "ingest",
            "chunk_route",
            inputs={
                "filename": context.filename,
                "structure_genre": (context.structure or {}).get("genre"),
                "document_genre": (context.classification or {}).get("document_genre"),
                "wizard_chunk_policy": process_config.get("chunk_policy"),
                "wizard_max_context_tokens": process_config.get("max_context_tokens"),
            },
            result={
                "academic_paper": academic,
                "reason": reason,
                "extractor": "extract_paper_units" if academic else "extract_units_from_text",
                "note": "confirm-strategy 路径走 configured_extraction；此处仅无快照时的兜底",
            },
        )
        if academic:
            return extract_paper_units(
                context,
                allowed_roles=self.ROLES,
                knowledge_type=KnowledgeType.TECHNICAL_CONCEPT,
            )
        return extract_units_from_text(
            context,
            allowed_roles=self.ROLES,
            knowledge_type=KnowledgeType.TECHNICAL_CONCEPT,
        )

    def plan(self, query: QueryContext) -> RetrievalPlan:
        roles = INTENT_ROLE_MAP.get(query.intent, [SemanticRole.DEFINITION, SemanticRole.EXPLANATION])
        graph = query.intent in {QueryIntent.SOLUTION, QueryIntent.CAUSE, QueryIntent.RISK, QueryIntent.COMPARISON}
        required_kinds = list(query.evidence_types or infer_evidence_types(query.query, query.intent.value))
        # 架构问 definition/principle 不够时，完整度按 required kinds 要图，而不是只查定义角色
        if is_architecture_query(query.query) and "figure" not in required_kinds:
            required_kinds = ["figure", "equation", "text"]
        expand_kinds = [kind for kind in required_kinds if kind in {"figure", "equation", "table"}] or [
            "figure",
            "equation",
            "table",
        ]
        return RetrievalPlan(
            intent=query.intent,
            topics=query.topics,
            required_roles=roles,
            graph_expand=graph or "figure" in required_kinds or "equation" in required_kinds,
            search_strategy="HYBRID",
            completeness_check=True,
            required_kinds=required_kinds,
            steps=[
                {"type": "catalog_filter", "domain": query.domain},
                {"type": "concept_search", "concepts": query.topics},
                {"type": "hybrid_search", "roles": [r.value for r in roles], "expand_kinds": expand_kinds},
                {"type": "completeness_check", "required_kinds": required_kinds},
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


def _is_academic_paper(context: DocumentContext) -> bool:
    academic, _reason = _academic_paper_decision(context)
    return academic


def _academic_paper_decision(context: DocumentContext) -> tuple[bool, str]:
    """抽取路由判定：优先 structure.genre，其次 classification，再看是否已有章节+公式/引用。"""
    structure = context.structure or {}
    classification = context.classification or {}
    if structure.get("genre") == "academic_paper":
        return True, "structure.genre=academic_paper"
    if classification.get("document_genre") == "academic_paper":
        return True, "classification.document_genre=academic_paper"
    if structure.get("sections") and (structure.get("citations") or structure.get("equations")):
        return True, "has_sections_and_citations_or_equations"
    return False, "generic_document"
