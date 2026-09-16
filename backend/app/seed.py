from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    KnowledgeLifecycle,
    KnowledgeType,
    QueryIntent,
    RelationType,
    SemanticRole,
    SourceLevel,
    UserRole,
)
from app.domain.ontology import flatten_ontology
from app.domain.extraction_policy import normalized_policy
from app.model_gateway.gateway import ModelGateway
from app.prompts.loader import apply_prompt_override, iter_prompt_files
from app.storage.es_store import ElasticStore
from app.storage.models import (
    Document,
    GoldenCase,
    KnowledgeAcl,
    KnowledgeBase,
    KnowledgeCatalog,
    KnowledgeRelation,
    KnowledgeStrategy,
    KnowledgeUnit,
    PromptTemplate,
    RetrievalPlannerConfig,
    User,
)
from app.storage.neo4j_store import Neo4jStore
from app.storage.qdrant_store import QdrantStore

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "cdc_design_guide.md"


async def sync_prompt_templates(session: AsyncSession) -> None:
    """把仓库芯片设计提示词写入模型中心表，并灌进运行时缓存。已有 prompt_id 则升级 content/version。"""
    existing = {
        item.prompt_id: item
        for item in (await session.execute(select(PromptTemplate))).scalars().all()
    }
    for data in iter_prompt_files():
        row = existing.get(data["prompt_id"])
        if row is None:
            row = PromptTemplate(
                prompt_id=data["prompt_id"],
                version=data["version"],
                strategy=data["strategy"],
                model=data["model"],
                temperature=data["temperature"],
                content=data["content"],
                input_schema=data["input_schema"],
                output_schema=data["output_schema"],
                status="production",
                success_rate=0.94,
            )
            session.add(row)
            apply_prompt_override(data["prompt_id"], data["content"])
            continue
        # 版本升级才覆盖，避免重启冲掉模型中心里已保存的芯片设计微调
        if row.version != data["version"]:
            row.version = data["version"]
            row.strategy = data["strategy"]
            row.model = data["model"]
            row.temperature = data["temperature"]
            row.content = data["content"]
            row.input_schema = data["input_schema"]
            row.output_schema = data["output_schema"]
            apply_prompt_override(data["prompt_id"], data["content"])
        else:
            apply_prompt_override(data["prompt_id"], row.content)
    await session.commit()


async def seed_if_empty(
    session: AsyncSession,
    gateway: ModelGateway,
    qdrant: QdrantStore,
    es_store: ElasticStore | None = None,
    neo4j_store: Neo4jStore | None = None,
) -> None:
    existing = await session.execute(select(KnowledgeBase).limit(1))
    if existing.scalar_one_or_none():
        return
    await seed_all(session, gateway, qdrant, es_store, neo4j_store)


async def seed_all(
    session: AsyncSession,
    gateway: ModelGateway,
    qdrant: QdrantStore,
    es_store: ElasticStore | None = None,
    neo4j_store: Neo4jStore | None = None,
) -> None:
    technical = KnowledgeStrategy(
        name="Technical Knowledge V1",
        version="V1",
        knowledge_type=KnowledgeType.TECHNICAL_CONCEPT.value,
        roles=[r.value for r in [
            SemanticRole.DEFINITION, SemanticRole.EXPLANATION, SemanticRole.PRINCIPLE,
            SemanticRole.FORMULA, SemanticRole.PARAMETER, SemanticRole.CONSTRAINT,
            SemanticRole.RULE, SemanticRole.EXAMPLE, SemanticRole.EXCEPTION, SemanticRole.REFERENCE,
            SemanticRole.SOLUTION, SemanticRole.CLASSIFICATION,
            SemanticRole.METRIC, SemanticRole.COMPARISON, SemanticRole.LIMITATION,
            SemanticRole.INTERFACE, SemanticRole.SUMMARY, SemanticRole.BACKGROUND,
        ]],
        chunk_policy="semantic_unit",
        extraction_policy=normalized_policy(None),
        retrieval_policy={
            "definition": ["definition", "explanation"],
            "cause_analysis": ["definition", "root_cause", "principle"],
            "solution": ["classification", "solution", "constraint", "example"],
            "risk_analysis": ["exception", "constraint", "root_cause", "prevention"],
        },
        completeness_policy={"minimum_coverage": 0.9, "low_coverage": "secondary_retrieval"},
        relation_schema={"definition": ["EXPLAINED_BY", "HAS_EXAMPLE", "HAS_EXCEPTION"]},
    )
    incident = KnowledgeStrategy(
        name="Incident Case V1",
        version="V1",
        knowledge_type=KnowledgeType.INCIDENT_CASE.value,
        roles=["environment", "symptom", "impact", "root_cause", "solution", "prevention"],
        extraction_policy=normalized_policy(None),
        retrieval_policy={"solution": ["symptom", "root_cause", "solution", "prevention"]},
        completeness_policy={"minimum_coverage": 0.8, "low_coverage": "secondary_retrieval"},
    )
    api = KnowledgeStrategy(
        name="API Document V1",
        version="V1",
        knowledge_type=KnowledgeType.API_DOCUMENT.value,
        roles=["definition", "api_input", "api_output", "error_code", "constraint", "example"],
        extraction_policy=normalized_policy(None),
        retrieval_policy={"definition": ["definition", "api_input", "api_output", "example"]},
        completeness_policy={"minimum_coverage": 0.9, "low_coverage": "return_warning"},
    )
    session.add_all([technical, incident, api])
    await session.flush()

    kb = KnowledgeBase(
        name="芯片设计知识库",
        description="存储芯片设计相关专业知识",
        domain="semiconductor",
        strategy_id=technical.id,
        access_scope="public",
    )
    session.add(kb)
    await session.flush()

    parent_ids: dict[str, str] = {}
    for row in flatten_ontology():
        parent_path = "/".join(row["path"].split("/")[:-1])
        node = KnowledgeCatalog(
            kb_id=kb.id,
            parent_id=parent_ids.get(parent_path),
            name=row["name"],
            path=row["path"],
            level=row["level"],
            related_concepts=row["related_concepts"],
        )
        session.add(node)
        await session.flush()
        parent_ids[row["path"]] = node.id

    users = [
        User(username="alice", display_name="Alice 用户", role=UserRole.END_USER.value, department="数字设计"),
        User(username="bob", display_name="Bob 专家", role=UserRole.KNOWLEDGE_EXPERT.value, department="数字设计"),
        User(username="carol", display_name="Carol 算法", role=UserRole.ALGORITHM_ENGINEER.value, department="平台"),
        User(username="admin", display_name="Admin", role=UserRole.ADMIN.value, department="平台"),
    ]
    session.add_all(users)
    await session.flush()
    session.add(KnowledgeAcl(kb_id=kb.id, principal_type="role", principal_id="end_user", permission="read"))
    session.add(KnowledgeAcl(kb_id=kb.id, principal_type="role", principal_id="knowledge_expert", permission="write"))

    for intent, steps in {
        QueryIntent.DEFINITION.value: [
            {"type": "query_analyze"}, {"type": "search_definition"}, {"type": "completeness_check"},
        ],
        QueryIntent.SOLUTION.value: [
            {"type": "query_analyze"}, {"type": "catalog_route"}, {"type": "hybrid_search"},
            {"type": "graph_expand"}, {"type": "rerank"}, {"type": "completeness_check"},
        ],
        QueryIntent.CAUSE.value: [
            {"type": "query_analyze"}, {"type": "search_cause"}, {"type": "hybrid_search"}, {"type": "completeness_check"},
        ],
        QueryIntent.COMPARISON.value: [
            {"type": "query_analyze"}, {"type": "hybrid_search"}, {"type": "completeness_check"},
        ],
        QueryIntent.RISK.value: [
            {"type": "query_analyze"}, {"type": "search_risk"}, {"type": "hybrid_search"}, {"type": "completeness_check"},
        ],
    }.items():
        session.add(
            RetrievalPlannerConfig(
                query_type=intent,
                steps=steps,
                completeness_threshold=0.8,
                secondary_retrieval=True,
            )
        )

    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8") if FIXTURE_PATH.exists() else ""
    doc = Document(
        kb_id=kb.id,
        filename="CDC Design Guide.md",
        object_key="seed/cdc_design_guide.md",
        mime_type="text/markdown",
        status="indexed",
        parse_progress=100,
        structure={
            "chapters": [{"title": "CDC", "level": 1, "page": 1}],
            "pages": [{"page": 1, "text": fixture_text[:8000]}],
        },
        classification={"knowledge_type": "technical_specification", "confidence": 0.93},
        recommended_strategy="Technical Knowledge V1",
        confirmed_strategy_id=technical.id,
        enabled=True,
    )
    session.add(doc)
    await session.flush()

    units_spec = [
        ("CDC 定义", SemanticRole.DEFINITION, "CDC（Clock Domain Crossing）是信号从一个时钟域传递到另一个异步时钟域的过程。", ["CDC"], "3.1", 12),
        ("亚稳态原理", SemanticRole.PRINCIPLE, "数据在接收时钟沿附近变化时，触发器可能进入亚稳态，并在后续逻辑中传播。", ["CDC", "Metastability"], "3.2", 13),
        ("亚稳态根因", SemanticRole.ROOT_CAUSE, "CDC 中产生亚稳态的主要原因是建立/保持时间无法满足。", ["Metastability", "Setup Time"], "3.2", 13),
        ("CDC 分类", SemanticRole.CLASSIFICATION, "CDC 问题可按单 bit、多 bit 和高速数据通路分类处理。", ["CDC"], "3.3", 14),
        ("双触发器同步器", SemanticRole.SOLUTION, "单 bit 信号推荐使用双触发器同步器；多 bit 数据推荐 Handshake 或 Async FIFO。", ["Synchronizer", "Async FIFO"], "3.3", 14),
        ("CDC 设计约束", SemanticRole.CONSTRAINT, "Synchronizer 必须放在接收时钟域，需要计算 MTBF 并满足 Timing Constraint。禁止对多 bit 总线直接两级同步。", ["MTBF", "Timing Constraint"], "3.4", 15),
        ("异步 FIFO 示例", SemanticRole.EXAMPLE, "异步 FIFO 使用 Gray Code 编码读写指针，再通过同步器传递到对端时钟域。", ["Async FIFO", "Gray Code"], "3.5", 16),
        ("同源时钟例外", SemanticRole.EXCEPTION, "当两个时钟同源且相位关系已知时，可采用相位同步，而不使用异步 FIFO。", ["CDC"], "3.6", 17),
        ("Setup Time 定义", SemanticRole.DEFINITION, "Setup Time 是数据必须在时钟有效边沿之前保持稳定的最小时间。", ["Setup Time"], "4.1", 21),
        ("Async FIFO 架构", SemanticRole.SOLUTION, "异步 FIFO 包括写指针、读指针、指针同步、满/空检测和复位。", ["Async FIFO"], "5.2", 30),
        ("复位与时序约束", SemanticRole.CONSTRAINT, "异步 FIFO 复位策略和指针同步路径必须满足 timing constraint。", ["Async FIFO", "Timing Constraint"], "5.2", 31),
    ]
    created: dict[str, KnowledgeUnit] = {}
    for title, role, content, concepts, chapter, page in units_spec:
        unit = KnowledgeUnit(
            kb_id=kb.id,
            document_id=doc.id,
            knowledge_type=KnowledgeType.TECHNICAL_CONCEPT.value,
            title=title,
            content=content,
            semantic_role=role.value,
            importance="core",
            domain="digital_design",
            sub_domain="cdc",
            concepts=concepts,
            parent_context=f"CDC Design Guide / {chapter}",
            source_chapter=chapter,
            source_section=title,
            source_page=page,
            source_span=content,
            lifecycle=KnowledgeLifecycle.PUBLISHED.value,
            source_level=SourceLevel.REVIEWED.value,
            confidence=0.96,
        )
        session.add(unit)
        await session.flush()
        created[title] = unit

    relations = [
        ("CDC 定义", "亚稳态原理", RelationType.CAUSES.value),
        ("亚稳态根因", "双触发器同步器", RelationType.SOLVES.value),
        ("双触发器同步器", "CDC 设计约束", RelationType.CONSTRAINS.value),
        ("CDC 定义", "异步 FIFO 示例", RelationType.HAS_EXAMPLE.value),
        ("CDC 设计约束", "同源时钟例外", RelationType.HAS_EXCEPTION.value),
        ("Setup Time 定义", "CDC 定义", RelationType.RELATED_TO.value),
    ]
    for src, dst, rel in relations:
        session.add(
            KnowledgeRelation(from_id=created[src].id, to_id=created[dst].id, relation_type=rel)
        )

    session.add_all(
        [
            GoldenCase(
                dataset_name="cdc-v1",
                question="什么是 CDC？",
                required_knowledge=["CDC 定义"],
                optional_knowledge=["亚稳态原理"],
                forbidden_knowledge=["PCIe Timing"],
                expected_roles=["definition"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="cdc-v1",
                question="如何解决 CDC 中的亚稳态问题？",
                required_knowledge=["CDC 定义", "亚稳态根因", "双触发器同步器", "异步 FIFO 示例", "CDC 设计约束"],
                optional_knowledge=["复位与时序约束"],
                forbidden_knowledge=["PCIe Timing"],
                expected_roles=["definition", "root_cause", "solution", "constraint"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="cdc-v1",
                question="什么是 Setup Time",
                required_knowledge=["Setup Time 定义"],
                optional_knowledge=[],
                forbidden_knowledge=[],
                expected_roles=["definition"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="jssc2016-hybrid-adc",
                question="为什么这种 ADC 可以降低数字均衡器功耗？",
                required_knowledge=["Fig. 4", "per-symbol", "bypass"],
                optional_knowledge=["metric"],
                forbidden_knowledge=[],
                expected_roles=["principle", "interface", "metric"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="jssc2016-hybrid-adc",
                question="α₋₁ 是怎么算的？",
                required_knowledge=["Equation (1)"],
                optional_knowledge=["Fig. 9"],
                forbidden_knowledge=[],
                expected_roles=["formula"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="jssc2016-hybrid-adc",
                question="Fig.10 的 ADC 怎么分级？",
                required_knowledge=["Fig. 10"],
                optional_knowledge=["32-way", "312.5 MS/s"],
                forbidden_knowledge=[],
                expected_roles=["interface"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="jssc2016-hybrid-adc",
                question="和先前 ADC-based receiver 比有什么指标？",
                required_knowledge=["TABLE I"],
                optional_knowledge=[],
                forbidden_knowledge=[],
                expected_roles=["metric", "comparison"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="jssc2016-hybrid-adc",
                question="ADC 里嵌 FFE 的相关先前工作是哪篇？",
                required_knowledge=["[12]"],
                optional_knowledge=[],
                forbidden_knowledge=[],
                expected_roles=["reference"],
                kb_id=kb.id,
            ),
            GoldenCase(
                dataset_name="jssc2016-hybrid-adc",
                question="论文 DOI 和发表信息？",
                required_knowledge=["DOI"],
                optional_knowledge=[],
                forbidden_knowledge=[],
                expected_roles=["summary"],
                kb_id=kb.id,
            ),
        ]
    )
    await session.commit()

    texts = [f"{u.title}\n{u.content}" for u in created.values()]
    vectors = gateway.embed(texts)
    for unit, vector in zip(created.values(), vectors, strict=False):
        qdrant.upsert(
            unit.id,
            vector,
            {
                "kb_id": unit.kb_id,
                "knowledge_type": unit.knowledge_type,
                "semantic_role": unit.semantic_role,
                "domain": unit.domain,
                "concept_ids": unit.concepts,
                "source_level": unit.source_level,
                "lifecycle": unit.lifecycle,
                "version": unit.version,
                "title": unit.title,
                "content": unit.content,
            },
        )
        if es_store:
            await es_store.upsert(
                unit.id,
                {
                    "title": unit.title,
                    "content": unit.content,
                    "concepts": unit.concepts,
                    "semantic_role": unit.semantic_role,
                    "kb_id": unit.kb_id,
                    "lifecycle": unit.lifecycle,
                    "knowledge_type": unit.knowledge_type,
                    "domain": unit.domain,
                },
            )
        if neo4j_store:
            neo4j_store.upsert_unit(
                {
                    "id": unit.id,
                    "title": unit.title,
                    "semantic_role": unit.semantic_role,
                    "domain": unit.domain,
                    "kb_id": unit.kb_id,
                    "lifecycle": unit.lifecycle,
                    "concepts": unit.concepts,
                }
            )
    if neo4j_store:
        for src, dst, rel in relations:
            neo4j_store.upsert_relation(created[src].id, created[dst].id, rel)
