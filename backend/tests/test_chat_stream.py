import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.api.schemas import ChatRequest

chat_api = importlib.import_module('app.api.chat')

@pytest.mark.asyncio
async def test_stream_delivers_events_and_images_before_done(monkeypatch):
    async def execute(payload, session, user, emit):
        await emit('status', {'stage': 'retrieve'})
        await emit('citations', {'citations': [{'image_key': 'figure.png', 'document_id': 'doc'}]})
        await emit('delta', {'text': '**回答**\n中文'})
        return {'answer': '**回答**\n中文', 'session_id': 's1'}
    monkeypatch.setattr(chat_api, '_execute_chat', execute)
    response = await chat_api.chat_stream(ChatRequest(query='问题'), AsyncMock(), SimpleNamespace(id='u'))
    frames = [frame async for frame in response.body_iterator]
    assert response.media_type == 'text/event-stream'
    assert response.headers['x-accel-buffering'] == 'no'
    assert 'event: citations' in frames[2] and 'figure.png' in frames[2]
    assert 'event: delta' in frames[3] and '中文' in frames[3]
    assert 'event: done' in frames[-1]

@pytest.mark.asyncio
async def test_stream_error_rolls_back_and_hides_internal_details(monkeypatch):
    async def execute(*args):
        raise ValueError('private connection string')
    monkeypatch.setattr(chat_api, '_execute_chat', execute)
    session = AsyncMock()
    response = await chat_api.chat_stream(ChatRequest(query='问题'), session, SimpleNamespace(id='u'))
    frames = [frame async for frame in response.body_iterator]
    assert 'event: error' in frames[-1]
    assert 'private' not in ''.join(frames)
    session.rollback.assert_awaited_once()

@pytest.mark.asyncio
async def test_stream_rejects_foreign_session():
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(user_id='someone-else')
    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_stream(ChatRequest(query='问题', session_id='s'), session, SimpleNamespace(id='u'))
    assert exc.value.status_code == 404

@pytest.mark.asyncio
async def test_stream_disconnect_cancels_work(monkeypatch):
    cancelled = asyncio.Event()
    async def execute(payload, session, user, emit):
        try:
            await emit('status', {'stage': 'answer'})
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(chat_api, '_execute_chat', execute)
    response = await chat_api.chat_stream(ChatRequest(query='问题'), AsyncMock(), SimpleNamespace(id='u'))
    iterator = response.body_iterator
    await anext(iterator)
    await anext(iterator)
    await iterator.aclose()
    assert cancelled.is_set()
