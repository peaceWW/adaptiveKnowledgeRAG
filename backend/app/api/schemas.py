from typing import Literal
from pydantic import BaseModel, Field, field_validator
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


class EvaluationCaseConfig(BaseModel):
    reference_answer: str = Field(default="", max_length=20000)
    answer_points: list[str] = Field(default_factory=list, max_length=50)
    expected_kinds: list[Literal["figure", "equation", "text", "table"]] = Field(default_factory=list)


class GoldenCaseCreate(BaseModel):
    dataset_name: str = Field(default="default", min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    required_knowledge: list[str] = Field(default_factory=list, max_length=100)
    optional_knowledge: list[str] = Field(default_factory=list, max_length=100)
    forbidden_knowledge: list[str] = Field(default_factory=list, max_length=100)
    expected_roles: list[str] = Field(default_factory=list)
    kb_id: str | None = None
    evaluation_config: EvaluationCaseConfig = Field(default_factory=EvaluationCaseConfig)

    @field_validator("dataset_name", "question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()

    @field_validator("required_knowledge", "optional_knowledge", "forbidden_knowledge")
    @classmethod
    def clean_evidence(cls, values):
        result = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        for value in result:
            if value.startswith(("id:", "keyword:", "title:")) and not value.split(":", 1)[1].strip():
                raise ValueError("证据标注不能为空")
            if value.startswith("anchor:") and ("#" not in value or not all(value[7:].split("#", 1))):
                raise ValueError("锚点格式为 anchor:文档ID#fig:4")
        return result


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
