from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(100), default="semiconductor")
    strategy_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_strategy.id"))
    access_scope: Mapped[str] = mapped_column(String(32), default="public")
    department: Mapped[str] = mapped_column(String(100), default="")
    project: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    strategy: Mapped[KnowledgeStrategy | None] = relationship(lazy="selectin")
    documents: Mapped[list[Document]] = relationship(back_populates="knowledge_base")


class KnowledgeStrategy(Base):
    __tablename__ = "knowledge_strategy"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(32), default="V1")
    knowledge_type: Mapped[str] = mapped_column(String(64))
    roles: Mapped[list[Any]] = mapped_column(JSON, default=list)
    chunk_policy: Mapped[str] = mapped_column(String(32), default="semantic_unit")
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=2000)
    retrieval_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completeness_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    relation_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="production")


class KnowledgeRole(Base):
    __tablename__ = "knowledge_role"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), default="CORE CONCEPTS")
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="#93c5fd")
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)


class KnowledgeCatalog(Base):
    __tablename__ = "knowledge_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kb_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_base.id"))
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_catalog.id"))
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(500), default="")
    level: Mapped[int] = mapped_column(Integer, default=0)
    domain: Mapped[str] = mapped_column(String(100), default="semiconductor")
    related_concepts: Mapped[list[Any]] = mapped_column(JSON, default=list)


class Document(Base):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_base.id"))
    filename: Mapped[str] = mapped_column(String(500))
    object_key: Mapped[str] = mapped_column(String(500), default="")
    mime_type: Mapped[str] = mapped_column(String(120), default="application/pdf")
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    parse_progress: Mapped[int] = mapped_column(Integer, default=0)
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    classification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recommended_strategy: Mapped[str] = mapped_column(String(200), default="")
    confirmed_strategy_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_strategy.id"))
    error_message: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    index_keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    index_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    units: Mapped[list[KnowledgeUnit]] = relationship(back_populates="document")


class KnowledgeUnit(Base):
    __tablename__ = "knowledge_unit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_base.id"))
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("document.id"))
    knowledge_type: Mapped[str] = mapped_column(String(64), default="technical_concept")
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    semantic_role: Mapped[str] = mapped_column(String(64))
    importance: Mapped[str] = mapped_column(String(32), default="core")
    domain: Mapped[str] = mapped_column(String(100), default="semiconductor")
    sub_domain: Mapped[str] = mapped_column(String(100), default="")
    concepts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    parent_context: Mapped[str] = mapped_column(String(500), default="")
    parent_id: Mapped[str | None] = mapped_column(String(36))
    source_chapter: Mapped[str] = mapped_column(String(64), default="")
    source_section: Mapped[str] = mapped_column(String(64), default="")
    source_page: Mapped[int] = mapped_column(Integer, default=0)
    source_span: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(32), default="v1.0")
    superseded_by: Mapped[str | None] = mapped_column(String(36))
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    lifecycle: Mapped[str] = mapped_column(String(32), default="DRAFT")
    source_level: Mapped[str] = mapped_column(String(32), default="AI_GENERATED")
    catalog_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_catalog.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document: Mapped[Document | None] = relationship(back_populates="units")


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    from_id: Mapped[str] = mapped_column(String(36))
    to_id: Mapped[str] = mapped_column(String(36))
    relation_type: Mapped[str] = mapped_column(String(64))
    from_kind: Mapped[str] = mapped_column(String(32), default="unit")
    to_kind: Mapped[str] = mapped_column(String(32), default="unit")


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    prompt_id: Mapped[str] = mapped_column(String(120), unique=True)
    version: Mapped[str] = mapped_column(String(32), default="V1")
    strategy: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.1)
    content: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="production")
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)


class ReviewTask(Base):
    __tablename__ = "review_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ku_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_unit.id"))
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("document.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("app_user.id"))
    title: Mapped[str] = mapped_column(String(300), default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class QueryTrace(Base):
    __tablename__ = "query_trace"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kb_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_base.id"))
    user_id: Mapped[str | None] = mapped_column(String(36))
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chat_session.id"))
    query: Mapped[str] = mapped_column(Text)
    understanding: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieval: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completeness: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    answer: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GoldenCase(Base):
    __tablename__ = "golden_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_name: Mapped[str] = mapped_column(String(200), default="default")
    question: Mapped[str] = mapped_column(Text)
    required_knowledge: Mapped[list[Any]] = mapped_column(JSON, default=list)
    optional_knowledge: Mapped[list[Any]] = mapped_column(JSON, default=list)
    forbidden_knowledge: Mapped[list[Any]] = mapped_column(JSON, default=list)
    expected_roles: Mapped[list[Any]] = mapped_column(JSON, default=list)
    kb_id: Mapped[str | None] = mapped_column(String(36))


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_name: Mapped[str] = mapped_column(String(200), default="default")
    strategy_name: Mapped[str] = mapped_column(String(200), default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    details: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(32), default="end_user")
    department: Mapped[str] = mapped_column(String(100), default="")
    project: Mapped[str] = mapped_column(String(100), default="")


class KnowledgeAcl(Base):
    __tablename__ = "knowledge_acl"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_base.id"))
    principal_type: Mapped[str] = mapped_column(String(32), default="role")
    principal_id: Mapped[str] = mapped_column(String(120))
    permission: Mapped[str] = mapped_column(String(32), default="read")


class RetrievalPlannerConfig(Base):
    __tablename__ = "retrieval_planner_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    query_type: Mapped[str] = mapped_column(String(64), unique=True)
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    completeness_threshold: Mapped[float] = mapped_column(Float, default=0.8)
    secondary_retrieval: Mapped[bool] = mapped_column(Boolean, default=True)
