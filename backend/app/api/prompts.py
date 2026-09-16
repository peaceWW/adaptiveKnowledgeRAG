from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PromptTest, PromptUpdate
from app.deps import get_stores
from app.prompts.loader import apply_prompt_override, prompt_catalog
from app.storage.db import get_session
from app.storage.models import PromptTemplate

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
async def list_prompts(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PromptTemplate))
    return [_serialize(p) for p in result.scalars().all()]


@router.put("/{prompt_pk}")
async def update_prompt(
    prompt_pk: str,
    payload: PromptUpdate,
    session: AsyncSession = Depends(get_session),
):
    prompt = await session.get(PromptTemplate, prompt_pk)
    if not prompt:
        raise HTTPException(404, "prompt not found")
    prompt.content = payload.content
    if payload.version:
        prompt.version = payload.version
    if payload.status:
        prompt.status = payload.status
    if payload.temperature is not None:
        prompt.temperature = payload.temperature
    await session.commit()
    apply_prompt_override(prompt.prompt_id, prompt.content)
    return _serialize(prompt)


@router.post("/{prompt_pk}/test")
async def test_prompt(
    prompt_pk: str,
    payload: PromptTest,
    session: AsyncSession = Depends(get_session),
):
    prompt = await session.get(PromptTemplate, prompt_pk)
    if not prompt:
        raise HTTPException(404, "prompt not found")
    stores = get_stores()
    result = stores.gateway.chat_json(payload.content or prompt.content, payload.input_text)
    return {"output": result}


def _serialize(prompt: PromptTemplate) -> dict:
    meta = prompt_catalog().get(prompt.prompt_id) or {}
    return {
        "id": prompt.id,
        "prompt_id": prompt.prompt_id,
        "title": meta.get("title") or prompt.prompt_id,
        "version": prompt.version,
        "strategy": prompt.strategy,
        "model": prompt.model,
        "temperature": prompt.temperature,
        "content": prompt.content,
        "status": prompt.status,
        "success_rate": prompt.success_rate,
        "input_schema": prompt.input_schema or {},
        "output_schema": prompt.output_schema or {},
    }
