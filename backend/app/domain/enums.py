from enum import StrEnum


class KnowledgeType(StrEnum):
    TECHNICAL_CONCEPT = "technical_concept"
    TECHNICAL_SPECIFICATION = "technical_specification"
    INCIDENT_CASE = "incident_case"
    API_DOCUMENT = "api_document"
    HISTORICAL_EVENT = "historical_event"
    ENTERPRISE_PROCESS = "enterprise_process"
    LEGAL_RULE = "legal_rule"
    UNKNOWN = "unknown"


class SemanticRole(StrEnum):
    DEFINITION = "definition"
    EXPLANATION = "explanation"
    PRINCIPLE = "principle"
    FORMULA = "formula"
    PARAMETER = "parameter"
    CONSTRAINT = "constraint"
    RULE = "rule"
    EXAMPLE = "example"
    EXCEPTION = "exception"
    REFERENCE = "reference"
    RELATED_CONCEPT = "related_concept"
    CLASSIFICATION = "classification"
    SOLUTION = "solution"
    ENVIRONMENT = "environment"
    SYMPTOM = "symptom"
    ROOT_CAUSE = "root_cause"
    PREVENTION = "prevention"
    IMPACT = "impact"
    API_INPUT = "api_input"
    API_OUTPUT = "api_output"
    ERROR_CODE = "error_code"
    REQUIREMENT = "requirement"
    ASSUMPTION = "assumption"
    PROCEDURE = "procedure"
    STEP = "step"
    ACTOR = "actor"
    SLA = "sla"
    WARNING = "warning"
    METRIC = "metric"
    COMPARISON = "comparison"
    BEST_PRACTICE = "best_practice"
    BACKGROUND = "background"
    SUMMARY = "summary"
    LIMITATION = "limitation"
    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    CLAUSE = "clause"
    TIMELINE = "timeline"
    DECISION = "decision"
    CONSEQUENCE = "consequence"
    SCOPE = "scope"
    INTERFACE = "interface"
    CHECKLIST = "checklist"


class KnowledgeLifecycle(StrEnum):
    DRAFT = "DRAFT"
    AI_PROCESSED = "AI_PROCESSED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class QueryIntent(StrEnum):
    DEFINITION = "definition"
    CAUSE = "cause_analysis"
    SOLUTION = "solution"
    RISK = "risk_analysis"
    COMPARISON = "comparison"
    UNKNOWN = "unknown"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    ANALYZED = "analyzed"
    AWAITING_STRATEGY = "awaiting_strategy"
    EXTRACTING = "extracting"
    REVIEW = "review"
    INDEXED = "indexed"
    FAILED = "failed"


class SourceLevel(StrEnum):
    OFFICIAL = "OFFICIAL"
    REVIEWED = "REVIEWED"
    INTERNAL = "INTERNAL"
    DRAFT = "DRAFT"
    AI_GENERATED = "AI_GENERATED"


class RelationType(StrEnum):
    DEPENDS_ON = "DEPENDS_ON"
    CAUSES = "CAUSES"
    SOLVES = "SOLVES"
    CONSTRAINS = "CONSTRAINS"
    RELATED_TO = "RELATED_TO"
    REFERENCES = "REFERENCES"
    SUPERSEDES = "SUPERSEDES"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    EXPLAINED_BY = "EXPLAINED_BY"
    HAS_EXAMPLE = "HAS_EXAMPLE"
    HAS_EXCEPTION = "HAS_EXCEPTION"
    AFFECTS = "AFFECTS"


class UserRole(StrEnum):
    END_USER = "end_user"
    KNOWLEDGE_EXPERT = "knowledge_expert"
    ALGORITHM_ENGINEER = "algorithm_engineer"
    ADMIN = "admin"


class AccessScope(StrEnum):
    PUBLIC = "public"
    DEPARTMENT = "department"
    PROJECT = "project"


class ChunkPolicy(StrEnum):
    SEMANTIC_UNIT = "semantic_unit"
    SECTION = "section"
    FIXED_TOKEN = "fixed_token"


HIGH_RISK_ROLES = {
    SemanticRole.RULE,
    SemanticRole.CONSTRAINT,
    SemanticRole.FORMULA,
    SemanticRole.EXCEPTION,
}

INTENT_ROLE_MAP: dict[QueryIntent, list[SemanticRole]] = {
    QueryIntent.DEFINITION: [
        SemanticRole.DEFINITION,
        SemanticRole.EXPLANATION,
    ],
    QueryIntent.CAUSE: [
        SemanticRole.DEFINITION,
        SemanticRole.ROOT_CAUSE,
        SemanticRole.PRINCIPLE,
        SemanticRole.SYMPTOM,
    ],
    QueryIntent.SOLUTION: [
        SemanticRole.CLASSIFICATION,
        SemanticRole.SOLUTION,
        SemanticRole.CONSTRAINT,
        SemanticRole.EXAMPLE,
        SemanticRole.RULE,
    ],
    QueryIntent.RISK: [
        SemanticRole.EXCEPTION,
        SemanticRole.CONSTRAINT,
        SemanticRole.ROOT_CAUSE,
        SemanticRole.PREVENTION,
    ],
}
