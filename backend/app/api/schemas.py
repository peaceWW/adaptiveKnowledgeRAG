from typing import Literal
from pydantic import BaseModel, Field
from app.domain.extraction_policy import ExtractionPolicy


class CatalogNodeCreate(BaseModel):
    name: str
    parent_id: str | None = None
    related_concepts: list[str] = Field(default_factory=list)


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = ""
    domain: str = "semiconductor"
    strategy_id: str | None = None
    access_scope: str = "public"
    department: str = ""
    project: str = ""


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    knowledge_type: str = "technical_concept"
    version: str = "V1"
    chunk_policy: Literal["semantic_unit", "section", "fixed_token"] | None = None
    roles: list[str] = Field(default_factory=list)
    clone_id: str | None = None
    completeness_policy: dict | None = None
    extraction_policy: ExtractionPolicy | None = None


class KnowledgeRoleCreate(BaseModel):
    key: str = ""
    label: str
    category: str = "CORE CONCEPTS"
    description: str = ""
    color: str = "#93c5fd"
    keywords: list[str] = Field(default_factory=list)


class StrategyPreviewRequest(BaseModel):
    roles: list[str] = Field(default_factory=list)
    text: str | None = None


class StrategyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    roles: list[str] | None = None
    chunk_policy: Literal["semantic_unit", "section", "fixed_token"] | None = None
    max_context_tokens: int | None = None
    retrieval_policy: dict | None = None
    completeness_policy: dict | None = None
    relation_schema: dict | None = None
    extraction_policy: ExtractionPolicy | None = None


class ReviewAction(BaseModel):
    action: str
    content: str | None = None
    title: str | None = None
    semantic_role: str | None = None
    importance: str | None = None
    confidence: float | None = None
    comment: str = ""


class ChatRequest(BaseModel):
    query: str
    kb_id: str | None = None
    session_id: str | None = None
    search_strategy: str = "adaptive"
    secondary: bool = False


class PromptUpdate(BaseModel):
    content: str
    version: str | None = None
    status: str | None = None
    temperature: float | None = None


class PromptTest(BaseModel):
    content: str
    input_text: str


class PlannerUpdate(BaseModel):
    query_type: str
    steps: list[dict]
    completeness_threshold: float = 0.8
    secondary_retrieval: bool = True


class KeywordIndexItem(BaseModel):
    keyword: str
    weight: float = 1.0
    source: str = "manual"


class DocumentIndexUpdate(BaseModel):
    keywords: list[KeywordIndexItem] | None = None
    metadata: dict | None = None


class KeywordDelete(BaseModel):
    keyword: str


class MetadataFieldDelete(BaseModel):
    key: str


class GoldenCaseCreate(BaseModel):
    dataset_name: str = "default"
    question: str
    required_knowledge: list[str] = Field(default_factory=list)
    optional_knowledge: list[str] = Field(default_factory=list)
    forbidden_knowledge: list[str] = Field(default_factory=list)
    expected_roles: list[str] = Field(default_factory=list)
    kb_id: str | None = None


class ConfirmStrategy(BaseModel):
    strategy_id: str
    knowledge_type: str | None = None
    chunk_policy: str | None = None
    max_context_tokens: int | None = None
    require_human_review: bool = True
    auto_enable: bool = False


class BatchReviewAction(BaseModel):
    unit_ids: list[str] = Field(default_factory=list)
    action: str = "accept"
    comment: str = ""
