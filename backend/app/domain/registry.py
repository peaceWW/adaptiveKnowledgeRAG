from __future__ import annotations

from app.domain.enums import KnowledgeType
from app.domain.strategies.api_doc import ApiDocumentStrategy
from app.domain.strategies.incident import IncidentCaseStrategy
from app.domain.strategies.technical import TechnicalKnowledgeStrategy
from app.domain.strategy import KnowledgeStrategy


class KnowledgeStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[KnowledgeType, KnowledgeStrategy] = {
            KnowledgeType.TECHNICAL_CONCEPT: TechnicalKnowledgeStrategy(),
            KnowledgeType.TECHNICAL_SPECIFICATION: TechnicalKnowledgeStrategy(),
            KnowledgeType.INCIDENT_CASE: IncidentCaseStrategy(),
            KnowledgeType.API_DOCUMENT: ApiDocumentStrategy(),
        }

    def get(self, knowledge_type: KnowledgeType | str) -> KnowledgeStrategy:
        if isinstance(knowledge_type, str):
            knowledge_type = KnowledgeType(knowledge_type)
        strategy = self._strategies.get(knowledge_type)
        if strategy is None:
            return self._strategies[KnowledgeType.TECHNICAL_CONCEPT]
        return strategy

    def all(self) -> dict[KnowledgeType, KnowledgeStrategy]:
        return self._strategies


registry = KnowledgeStrategyRegistry()
