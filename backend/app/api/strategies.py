from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import KnowledgeRoleCreate, StrategyCreate, StrategyPreviewRequest, StrategyUpdate
from app.domain.registry import registry
from app.domain.roles import PREVIEW_SAMPLE, ROLE_CATALOG, ROLE_LABELS, CATEGORY_LABELS
from app.domain.extraction_policy import normalized_policy
from app.storage.db import get_session
from app.storage.models import EvaluationRun, KnowledgeRole, KnowledgeStrategy

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _role_item(role: KnowledgeRole) -> dict:
    return {
        "id": role.id,
        "key": role.key,
        "label": ROLE_LABELS.get(role.key, role.label) if role.is_builtin else role.label,
        "category": CATEGORY_LABELS.get(role.category, role.category),
        "description": role.description,
        "color": role.color,
        "keywords": role.keywords or [],
        "is_builtin": bool(role.is_builtin),
    }


def _serialize(strategy: KnowledgeStrategy) -> dict:
    return {
        "id": strategy.id,
        "name": strategy.name,
        "version": strategy.version,
        "knowledge_type": strategy.knowledge_type,
        "roles": strategy.roles,
        "chunk_policy": strategy.chunk_policy,
        "extraction_policy": normalized_policy(strategy.extraction_policy),
        "max_context_tokens": strategy.max_context_tokens,
        "retrieval_policy": strategy.retrieval_policy,
        "completeness_policy": strategy.completeness_policy,
        "relation_schema": strategy.relation_schema,
        "status": strategy.status,
    }


def _slug(value: str) -> str:
    raw = (value or "").strip().lower().replace(" ", "_")
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw)
    return cleaned.strip("_") or "role"


async def _ensure_roles(session: AsyncSession) -> None:
    existing = set((await session.execute(select(KnowledgeRole.key))).scalars().all())
    session.add_all(
        [
            KnowledgeRole(
                key=item["key"],
                label=item["label"],
                category=item["category"],
                description=item["description"],
                color=item["color"],
                keywords=item["keywords"],
                is_builtin=True,
            )
            for item in ROLE_CATALOG
            if item["key"] not in existing
        ]
    )
    await session.commit()


def _annotate(text: str, roles: list[KnowledgeRole], selected: set[str]) -> tuple[list[dict], dict[str, int]]:
    spans: list[dict] = []
    counts: dict[str, int] = {}
    used: set[tuple[int, int]] = set()
    for role in roles:
        if role.key not in selected:
            continue
        for keyword in role.keywords or [role.label]:
            needle = str(keyword)
            if not needle:
                continue
            start = 0
            lowered = text
            while True:
                idx = lowered.find(needle, start)
                if idx < 0:
                    break
                end = idx + len(needle)
                if any(not (end <= a or idx >= b) for a, b in used):
                    start = end
                    continue
                used.add((idx, end))
                spans.append(
                    {
                        "start": idx,
                        "end": end,
                        "role": role.key,
                        "label": role.label,
                        "color": role.color,
                        "text": text[idx:end],
                    }
                )
                counts[role.key] = counts.get(role.key, 0) + 1
                start = end
    spans.sort(key=lambda item: item["start"])
    return spans, counts


@router.get("")
async def list_strategies(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(KnowledgeStrategy))
    return [_serialize(s) for s in result.scalars().all()]


@router.post("")
async def create_strategy(payload: StrategyCreate, session: AsyncSession = Depends(get_session)):
    source = None
    if payload.clone_id:
        source = await session.get(KnowledgeStrategy, payload.clone_id)
        if not source:
            raise HTTPException(404, "被复制的策略不存在")
    roles = payload.roles or (source.roles if source else ["definition", "explanation", "principle", "constraint", "example"])
    strategy = KnowledgeStrategy(
        name=payload.name.strip(),
        version=payload.version or (source.version if source else "V1"),
        knowledge_type=payload.knowledge_type or (source.knowledge_type if source else "technical_concept"),
        roles=list(roles),
        chunk_policy=payload.chunk_policy or (source.chunk_policy if source else "semantic_unit"),
        extraction_policy=payload.extraction_policy.model_dump() if payload.extraction_policy else normalized_policy(source.extraction_policy if source else None),
        max_context_tokens=source.max_context_tokens if source else 2000,
        retrieval_policy=dict(source.retrieval_policy) if source else {},
        completeness_policy=payload.completeness_policy
        or (dict(source.completeness_policy) if source else {"minimum_coverage": 0.9, "low_coverage": "secondary_retrieval"}),
        relation_schema=dict(source.relation_schema) if source else {},
        status="draft",
    )
    await _validate_strategy(session, strategy.name, strategy.roles, strategy.completeness_policy, strategy.extraction_policy)
    session.add(strategy)
    await session.commit()
    await session.refresh(strategy)
    return _serialize(strategy)


@router.get("/roles")
async def list_roles(session: AsyncSession = Depends(get_session)):
    await _ensure_roles(session)
    result = await session.execute(select(KnowledgeRole).order_by(KnowledgeRole.category, KnowledgeRole.key))
    return [_role_item(role) for role in result.scalars().all()]


@router.post("/roles")
async def create_role(payload: KnowledgeRoleCreate, session: AsyncSession = Depends(get_session)):
    await _ensure_roles(session)
    key = _slug(payload.key or payload.label)
    exists = await session.execute(select(KnowledgeRole).where(KnowledgeRole.key == key))
    if exists.scalar_one_or_none():
        raise HTTPException(400, f"role already exists: {key}")
    role = KnowledgeRole(
        key=key,
        label=payload.label.strip() or key,
        category=payload.category or "CORE CONCEPTS",
        description=payload.description,
        color=payload.color or "#93c5fd",
        keywords=payload.keywords or [payload.label],
        is_builtin=False,
    )
    session.add(role)
    await session.commit()
    await session.refresh(role)
    return _role_item(role)


@router.post("/preview")
async def preview_strategy(payload: StrategyPreviewRequest, session: AsyncSession = Depends(get_session)):
    await _ensure_roles(session)
    roles = (await session.execute(select(KnowledgeRole))).scalars().all()
    text = (payload.text or PREVIEW_SAMPLE).strip()
    selected = set(payload.roles)
    spans, counts = _annotate(text, list(roles), selected)
    total = max(sum(counts.values()), 1)
    distribution = [
        {
            "role": role.key,
            "label": role.label,
            "color": role.color,
            "count": counts.get(role.key, 0),
            "percent": round(counts.get(role.key, 0) * 100 / total, 1),
        }
        for role in roles
        if role.key in selected and counts.get(role.key)
    ]
    distribution.sort(key=lambda item: item["percent"], reverse=True)
    threshold = 0.9
    run = (await session.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))).scalars().first()
    if run and run.metrics:
        metrics = {
            "precision": round(float(run.metrics.get("groundedness") or 0.88), 2),
            "recall": round(float(run.metrics.get("recall") or 0.75), 2),
            "f1": round(float(run.metrics.get("coverage") or 0.81), 2),
            "source": "evaluation",
        }
    else:
        recall = min(0.95, 0.52 + 0.03 * len(selected))
        precision = min(0.95, 0.62 + 0.25 * threshold - 0.008 * max(len(selected) - 8, 0))
        f1 = 0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        metrics = {
            "precision": round(precision, 2),
            "recall": round(recall, 2),
            "f1": round(f1, 2),
            "source": "estimated",
        }
    return {
        "text": text,
        "spans": spans,
        "distribution": distribution,
        "metrics": metrics,
        "legend": [{"role": item["role"], "label": item["label"], "color": item["color"]} for item in distribution[:6]],
    }


@router.get("/runtime")
async def runtime_strategies():
    return [
        {"knowledge_type": t.value, "ontology": s.ontology()}
        for t, s in registry.all().items()
    ]


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str, session: AsyncSession = Depends(get_session)):
    strategy = await session.get(KnowledgeStrategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "strategy not found")
    return _serialize(strategy)


@router.put("/{strategy_id}")
async def update_strategy(
    strategy_id: str,
    payload: StrategyUpdate,
    session: AsyncSession = Depends(get_session),
):
    strategy = await session.get(KnowledgeStrategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "strategy not found")
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in data:
        data["name"] = data["name"].strip()
    await _validate_strategy(session, data.get("name", strategy.name), data.get("roles", strategy.roles),
                             data.get("completeness_policy", strategy.completeness_policy),
                             data.get("extraction_policy", normalized_policy(strategy.extraction_policy)))
    for key, value in data.items():
        setattr(strategy, key, value)
    await session.commit()
    await session.refresh(strategy)
    return _serialize(strategy)


async def _validate_strategy(session, name, roles, completeness, policy):
    if not name:
        raise HTTPException(422, "策略名称不能为空")
    await _ensure_roles(session)
    known = set((await session.execute(select(KnowledgeRole.key))).scalars().all())
    if set(roles or []) - known:
        raise HTTPException(422, "存在未知知识类别，请先添加自定义类别")
    if policy.get("text") and not (set(roles or []) - {"formula", "reference"}):
        raise HTTPException(422, "启用文本提取时，请至少选择一种文本知识类别")
    try:
        threshold = float((completeness or {}).get("minimum_coverage", 0.9))
        if not 0 <= threshold <= 1:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(422, "完整性阈值必须在 0 到 1 之间")
