import importlib
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

api = importlib.import_module('app.api.retrieval')


def rows(items):
    result = Mock()
    result.scalars.return_value.all.return_value = items
    result.all.return_value = items
    return result


def test_request_rejects_blank_query_and_invalid_limit():
    for payload in [{'query': '   ', 'kb_id': 'k'}, {'query': 'SAR', 'kb_id': 'k', 'top_k': 0}, {'query': 'SAR', 'kb_id': 'k', 'top_k': 21}]:
        with pytest.raises(ValidationError):
            api.RetrievalTestRequest(**payload)
    assert api.RetrievalTestRequest(query=' SAR ', kb_id='k').query == 'SAR'


@pytest.mark.asyncio
async def test_preflight_uses_retrieval_only_and_preserves_provenance(monkeypatch):
    session = AsyncMock()
    session.get.return_value = NS(id='k', name='芯片库', access_scope='public')
    doc = NS(id='d', filename='receiver.pdf', index_meta={'title': 'Receiver'})
    session.execute.side_effect = [rows([]), rows([doc])]
    workflow = NS(understand=AsyncMock(side_effect=lambda s: {**s, 'understanding': {'intent': 'definition'}}),
                  plan=AsyncMock(side_effect=lambda s: {**s, 'plan': {'required_roles': ['principle']}}),
                  retrieve=AsyncMock(side_effect=lambda s: {**s, 'hits': [{'id': 'u1', 'document_id': 'd', 'source_page': 2, 'image_key': 'images/d/fig.png'}, {'id': 'u2'}], 'retrieval': {'reranked': 2}}),
                  answer=AsyncMock(), complete=AsyncMock())
    monkeypatch.setattr(api, 'QueryWorkflow', Mock(return_value=workflow))
    monkeypatch.setattr(api, 'get_stores', lambda: NS(gateway=NS(client=None), qdrant=NS(available=False), es=NS(available=False), neo4j=NS(available=False)))
    data = await api.test_retrieval(api.RetrievalTestRequest(query='SAR', kb_id='k', top_k=1), session, NS(id='u', role='admin'))
    assert len(data['hits']) == 1 and data['total'] == 2
    assert data['hits'][0]['document_title'] == 'Receiver'
    assert data['hits'][0]['source_page'] == 2
    assert data['hits'][0]['image_key'] == 'images/d/fig.png'
    assert [s['key'] for s in data['stages']] == ['understand', 'plan', 'retrieve']
    assert data['services']['model'] is False
    workflow.answer.assert_not_awaited()
    workflow.complete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_scope_is_rejected_before_retrieval(monkeypatch):
    session = AsyncMock()
    session.get.return_value = NS(id='k', access_scope='private')
    session.execute.return_value = rows([])
    stores = Mock()
    monkeypatch.setattr(api, 'get_stores', stores)
    with pytest.raises(HTTPException) as error:
        await api.test_retrieval(api.RetrievalTestRequest(query='SAR', kb_id='k'), session, NS(id='u', role='end_user', department='', project=''))
    assert error.value.status_code == 403
    stores.assert_not_called()


@pytest.mark.asyncio
async def test_index_browsing_does_not_regenerate_cleared_metadata(monkeypatch):
    session = AsyncMock()
    doc = NS(id='d', kb_id='k', filename='receiver.pdf', status='review', enabled=False, index_keywords=[], index_meta={})
    session.execute.side_effect = [rows([doc]), rows([('d', 2)])]
    monkeypatch.setattr(api, 'unit_count_map', AsyncMock(return_value={'d': 3}))
    data = await api.list_indexes(session=session)
    assert data[0]['keywords'] == [] and data[0]['metadata'] == {}
    assert data[0]['unit_count'] == 3 and data[0]['retrievable_count'] == 2
    session.commit.assert_not_awaited()


def test_keyword_zero_weight_is_preserved():
    from app.retrieval.doc_index import normalize_keywords
    assert normalize_keywords([{'keyword': 'SAR', 'weight': 0}])[0]['weight'] == 0
