from datetime import datetime, timedelta
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChatRequest
from app.config import get_settings
from app.deps import current_user, get_stores
from app.retrieval.workflow import QueryWorkflow
from app.storage.db import get_session
from app.storage.models import ChatSession, QueryTrace, User

router = APIRouter(prefix="/chat", tags=["chat"])


def _title_from_query(query: str) -> str:
    text = " ".join(query.strip().split())
    return text[:28] + ("…" if len(text) > 28 else "") or "新会话"


def _format_time(created_at: datetime | None) -> str:
    if not created_at:
        return ""
    now = datetime.now()
    if created_at.date() == now.date():
        return created_at.strftime("%H:%M")
    if created_at.date() == now.date() - timedelta(days=1):
        return "昨天"
    return created_at.strftime("%m/%d")


def _serialize_trace(trace: QueryTrace) -> dict:
    return {
        "id": trace.id,
        "trace_id": trace.id,
        "query": trace.query,
        "answer": trace.answer,
        "citations": trace.citations or [],
        "understanding": trace.understanding or {},
        "plan": trace.plan or {},
        "retrieval": trace.retrieval or {},
        "completeness": trace.completeness or {},
        "confidence": trace.confidence or {},
        "hits": (trace.retrieval or {}).get("hits") or [],
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


def _payload_from_result(result: dict, elapsed_ms: int) -> dict:
    settings = get_settings()
    hits = result.get("hits") or []
    return {
        "trace_id": result.get("trace_id"),
        "answer": result.get("answer"),
        "citations": result.get("citations") or [],
        "understanding": result.get("understanding") or {},
        "plan": result.get("plan") or {},
        "retrieval": result.get("retrieval") or {},
        "completeness": result.get("completeness") or {},
        "confidence": result.get("confidence") or {},
        "hits": hits,
        "elapsed_ms": elapsed_ms,
        "tokens": max(len((result.get("answer") or "")) // 4, 1),
        "model": settings.model_llm,
    }


@router.get("/sessions")
async def list_sessions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    result = await session.execute(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc())
    )
    return [
        {
            "id": item.id,
            "title": item.title,
            "time": _format_time(item.updated_at or item.created_at),
        }
        for item in result.scalars().all()
    ]


@router.post("/sessions")
async def create_session(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    item = ChatSession(user_id=user.id, title="新会话")
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "title": item.title, "time": _format_time(item.updated_at)}


@router.delete("/sessions")
async def clear_sessions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    owned = (
        await session.execute(select(ChatSession).where(ChatSession.user_id == user.id))
    ).scalars().all()
    ids = [item.id for item in owned]
    if ids:
        traces = await session.execute(select(QueryTrace).where(QueryTrace.session_id.in_(ids)))
        for trace in traces.scalars().all():
            await session.delete(trace)
        for item in owned:
            await session.delete(item)
        await session.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    chat = await session.get(ChatSession, session_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(404, "session not found")
    traces = (
        await session.execute(
            select(QueryTrace).where(QueryTrace.session_id == session_id).order_by(QueryTrace.created_at.asc())
        )
    ).scalars().all()
    last = traces[-1] if traces else None
    return {
        "id": chat.id,
        "title": chat.title,
        "turns": [_serialize_trace(item) for item in traces],
        "latest": _serialize_trace(last) if last else None,
    }


@router.post("")
async def chat(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    stores = get_stores()
    chat_session = None
    if payload.session_id:
        chat_session = await session.get(ChatSession, payload.session_id)
        if chat_session and chat_session.user_id != user.id:
            raise HTTPException(403, "session forbidden")
    if chat_session is None:
        chat_session = ChatSession(user_id=user.id, title=_title_from_query(payload.query))
        session.add(chat_session)
        await session.flush()
    started = perf_counter()
    workflow = QueryWorkflow(session, stores.gateway, stores.qdrant, stores.es, stores.neo4j)
    result = await workflow.run(payload.query, payload.kb_id, user.id)
    elapsed_ms = int((perf_counter() - started) * 1000)
    if result.get("trace_id"):
        trace = await session.get(QueryTrace, result["trace_id"])
        if trace:
            trace.session_id = chat_session.id
            retrieval = dict(trace.retrieval or {})
            retrieval["hits"] = result.get("hits") or []
            retrieval["search_strategy"] = payload.search_strategy
            trace.retrieval = retrieval
    if chat_session.title in {"新会话", ""}:
        chat_session.title = _title_from_query(payload.query)
    chat_session.updated_at = datetime.now()
    await session.commit()
    body = _payload_from_result(result, elapsed_ms)
    body["session_id"] = chat_session.id
    plan = dict(body.get("plan") or {})
    plan["search_strategy"] = payload.search_strategy
    body["plan"] = plan
    return body


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, session: AsyncSession = Depends(get_session)):
    trace = await session.get(QueryTrace, trace_id)
    if not trace:
        return {}
    return _serialize_trace(trace)
