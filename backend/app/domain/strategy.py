from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.enums import KnowledgeType, QueryIntent, SemanticRole


@dataclass
class DocumentContext:
    document_id: str
    filename: str
    text: str
    structure: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)
    gateway: Any = None
    raw: bytes | None = None
    minio: Any = None
    extraction_policy: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeUnitDraft:
    title: str
    content: str
    semantic_role: SemanticRole
    knowledge_type: KnowledgeType
    importance: str = "core"
    concepts: list[str] = field(default_factory=list)
    source_span: str = ""
    source_chapter: str = ""
    source_section: str = ""
    source_page: int = 0
    parent_context: str = ""
    confidence: float = 0.8
    relations: list[dict[str, Any]] = field(default_factory=list)
    unit_meta: dict[str, Any] = field(default_factory=dict)
    source_level: str = ""


@dataclass
class QueryContext:
    query: str
    kb_id: str | None = None
    domain: str = "semiconductor"
    intent: QueryIntent = QueryIntent.UNKNOWN
    topics: list[str] = field(default_factory=list)
    user_role: str = "end_user"
    department: str = ""
    project: str = ""
    evidence_types: list[str] = field(default_factory=list)


@dataclass
class RetrievalPlan:
    intent: QueryIntent
    topics: list[str]
    required_roles: list[SemanticRole]
    graph_expand: bool
    search_strategy: str
    completeness_check: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    required_kinds: list[str] = field(default_factory=list)


@dataclass
class CompletenessResult:
    required_knowledge: list[str]
    covered: list[str]
    missing: list[str]
    completeness_score: float
    need_secondary_retrieval: bool
    secondary_query: str = ""


class KnowledgeStrategy(Protocol):
    def type(self) -> KnowledgeType: ...

    def ontology(self) -> dict[str, Any]: ...

    def build_units(self, context: DocumentContext) -> list[KnowledgeUnitDraft]: ...

    def plan(self, query: QueryContext) -> RetrievalPlan: ...

    def check_completeness(
        self, query: QueryContext, retrieved_roles: list[str], retrieved_titles: list[str]
    ) -> CompletenessResult: ...
