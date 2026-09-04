from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import GoldenCaseCreate
from app.deps import current_user, get_stores
from app.retrieval.workflow import QueryWorkflow
from app.storage.db import get_session
from app.storage.models import EvaluationRun, GoldenCase, KnowledgeStrategy, User

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def classify_question(question: str, expected_roles: list | None = None) -> str:
    text = question or ""
    roles = {str(item) for item in (expected_roles or [])}
    if any(k in text for k in ["什么是", "何为", "定义"]) or "definition" in roles:
        return "定义类"
    if any(k in text for k in ["如何", "怎么", "解决", "推荐"]) or "solution" in roles:
        return "解决方案类"
    if any(k in text for k in ["为什么", "原因", "解释"]) or "explanation" in roles or "root_cause" in roles:
        return "解释类"
    if any(k in text for k in ["对比", "比较", "区别", "vs"]):
        return "比较类"
    return "其他"


def _avg(values: list[float]) -> float:
    return round(sum(values) / max(len(values), 1), 3)


@router.get("/golden")
async def list_golden(dataset_name: str | None = None, session: AsyncSession = Depends(get_session)):
    stmt = select(GoldenCase)
    if dataset_name:
        stmt = stmt.where(GoldenCase.dataset_name == dataset_name)
    result = await session.execute(stmt)
    return [_serialize(c) for c in result.scalars().all()]


@router.post("/golden")
async def create_golden(payload: GoldenCaseCreate, session: AsyncSession = Depends(get_session)):
    case = GoldenCase(**payload.model_dump())
    session.add(case)
    await session.commit()
    await session.refresh(case)
    return _serialize(case)


@router.post("/run")
async def run_evaluation(
    dataset_name: str = "cdc-v1",
    strategy_name: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    stores = get_stores()
    result = await session.execute(select(GoldenCase).where(GoldenCase.dataset_name == dataset_name))
    cases = result.scalars().all()
    if strategy_name:
        name = strategy_name
    else:
        strategy = (await session.execute(select(KnowledgeStrategy).limit(1))).scalar_one_or_none()
        name = strategy.name if strategy else "Technical Knowledge V1"
    workflow = QueryWorkflow(session, stores.gateway, stores.qdrant, stores.es, stores.neo4j)
    details = []
    recall_scores = []
    precision_scores = []
    mrr_scores = []
    coverage_scores = []
    grounded = []
    forbidden_hits = 0
    for case in cases:
        output = await workflow.run(case.question, case.kb_id, user.id)
        hits = output.get("hits") or []
        titles = [h.get("title") for h in hits]
        required = case.required_knowledge or []
        optional = case.optional_knowledge or []
        relevant = set(required + optional)
        top10 = titles[:10]
        hit_required = [t for t in top10 if t in required]
        recall = len(hit_required) / max(len(required), 1)
        precision = len([t for t in top10 if t in relevant]) / max(len(top10), 1)
        rank = next((i + 1 for i, title in enumerate(titles) if title in required), None)
        mrr = 1 / rank if rank else 0.0
        coverage = float((output.get("completeness") or {}).get("completeness_score") or recall)
        forbidden = [t for t in (case.forbidden_knowledge or []) if t in titles]
        forbidden_hits += len(forbidden)
        citations = output.get("citations") or []
        grounded.append(1.0 if citations else 0.0)
        recall_scores.append(recall)
        precision_scores.append(precision)
        mrr_scores.append(mrr)
        coverage_scores.append(coverage)
        details.append(
            {
                "question": case.question,
                "question_type": classify_question(case.question, case.expected_roles),
                "recall": round(recall, 3),
                "precision": round(precision, 3),
                "mrr": round(mrr, 3),
                "coverage": round(coverage, 3),
                "forbidden": forbidden,
                "pass": recall >= 0.8 and not forbidden,
            }
        )
    metrics = {
        "recall": _avg(recall_scores),
        "precision": _avg(precision_scores),
        "mrr": _avg(mrr_scores),
        "coverage": _avg(coverage_scores),
        "groundedness": _avg(grounded),
        "forbidden_hits": forbidden_hits,
        "cases": len(cases),
        "pass_rate": round(sum(1 for item in details if item["pass"]) / max(len(details), 1), 3),
    }
    run = EvaluationRun(dataset_name=dataset_name, strategy_name=name, metrics=metrics, details=details)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return {
        "id": run.id,
        "metrics": metrics,
        "details": details,
        "strategy_name": name,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/overview")
async def overview(
    dataset_name: str | None = None,
    strategy_name: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    cases = (await session.execute(select(GoldenCase))).scalars().all()
    datasets = sorted({case.dataset_name for case in cases if case.dataset_name})
    runs = (await session.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))).scalars().all()
    if dataset_name:
        runs = [run for run in runs if run.dataset_name == dataset_name]
        cases = [case for case in cases if case.dataset_name == dataset_name]
    if strategy_name:
        runs = [run for run in runs if run.strategy_name == strategy_name]
    latest = runs[0] if runs else None
    previous = runs[1] if len(runs) > 1 else None
    kpis = _kpis(latest.metrics if latest else None, previous.metrics if previous else None)
    trend = []
    for run in reversed(runs[:7]):
        metrics = run.metrics or {}
        trend.append(
            {
                "date": run.created_at.strftime("%m-%d") if run.created_at else "",
                "recall": round(float(metrics.get("recall") or 0) * 100, 1),
                "precision": round(float(metrics.get("precision") or 0) * 100, 1),
                "coverage": round(float(metrics.get("coverage") or 0) * 100, 1),
            }
        )
    type_source = []
    if latest and latest.details:
        for item in latest.details:
            type_source.append(
                {
                    **item,
                    "question_type": item.get("question_type")
                    or classify_question(item.get("question") or ""),
                }
            )
    else:
        type_source = [
            {"question_type": classify_question(case.question, case.expected_roles)} for case in cases
        ]
    counts = Counter(item.get("question_type") or "其他" for item in type_source)
    total = max(sum(counts.values()), 1)
    palette = {
        "定义类": "#1d4ed8",
        "解释类": "#60a5fa",
        "解决方案类": "#22c55e",
        "比较类": "#f97316",
        "其他": "#94a3b8",
    }
    question_types = [
        {
            "label": label,
            "count": count,
            "percent": round(count * 100 / total),
            "color": palette.get(label, "#94a3b8"),
        }
        for label, count in counts.most_common()
    ]
    by_strategy: dict[str, dict] = {}
    for run in runs:
        if run.strategy_name not in by_strategy:
            by_strategy[run.strategy_name] = {
                "strategy_name": run.strategy_name,
                "metrics": run.metrics,
                "created_at": run.created_at.isoformat() if run.created_at else "",
            }
    return {
        "datasets": datasets or ["cdc-v1"],
        "kpis": kpis,
        "trend": trend,
        "question_types": question_types,
        "total_questions": len(type_source),
        "latest": _run_item(latest) if latest else None,
        "runs": [_run_item(run) for run in runs[:20]],
        "strategy_compare": list(by_strategy.values()),
        "golden_count": len(cases),
    }


@router.get("/runs")
async def list_runs(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))
    return [_run_item(r) for r in result.scalars().all()]


def _kpis(current: dict | None, previous: dict | None) -> dict:
    current = current or {}
    previous = previous or {}

    def pack(key: str, as_percent: bool = True) -> dict:
        now = float(current.get(key) or 0)
        old = float(previous.get(key) or 0)
        delta = now - old
        return {
            "value": round(now * 100, 1) if as_percent else round(now, 2),
            "delta": round(delta * 100, 1) if as_percent else round(delta, 2),
            "up": delta >= 0,
        }

    return {
        "recall": pack("recall"),
        "precision": pack("precision"),
        "mrr": pack("mrr", as_percent=False),
        "coverage": pack("coverage"),
        "groundedness": pack("groundedness"),
        "pass_rate": pack("pass_rate"),
    }


def _run_item(run: EvaluationRun | None) -> dict:
    if not run:
        return {}
    return {
        "id": run.id,
        "dataset_name": run.dataset_name,
        "strategy_name": run.strategy_name,
        "metrics": run.metrics,
        "details": run.details,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _serialize(case: GoldenCase) -> dict:
    return {
        "id": case.id,
        "dataset_name": case.dataset_name,
        "question": case.question,
        "required_knowledge": case.required_knowledge,
        "optional_knowledge": case.optional_knowledge,
        "forbidden_knowledge": case.forbidden_knowledge,
        "expected_roles": case.expected_roles,
        "kb_id": case.kb_id,
        "question_type": classify_question(case.question, case.expected_roles),
    }
