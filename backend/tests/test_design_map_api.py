import importlib
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

api = importlib.import_module('app.api.graph')


def result(items):
    value = Mock()
    value.scalars.return_value.all.return_value = items
    return value


def user(role='end_user'):
    return NS(id='user-1', role=role, department='design', project='rx')


def kb(id, scope):
    return NS(id=id, name=id, access_scope=scope, department='', project='')


@pytest.mark.asyncio
async def test_design_endpoint_filters_private_bases_and_empty_access():
    session = AsyncMock()
    session.execute.side_effect = [result([kb('private', 'private')]), result([]), result([]), result([])]
    data = await api.design_map('', session, user())
    assert data['knowledge_bases'] == []
    assert data['summary']['units'] == 0
    params = session.execute.call_args_list[2].args[0].compile().params
    assert [] in params.values()  # Explicit empty IN, never an unscoped fallback.


@pytest.mark.asyncio
async def test_design_endpoint_rejects_unauthorized_explicit_scope():
    session = AsyncMock()
    session.execute.side_effect = [result([kb('private', 'private')]), result([])]
    with pytest.raises(HTTPException) as error:
        await api.design_map('private', session, user())
    assert error.value.status_code == 403
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_design_endpoint_honors_explicit_read_acl():
    session = AsyncMock()
    rule = NS(kb_id='private', permission='read', principal_type='user', principal_id='user-1')
    session.execute.side_effect = [result([kb('private', 'private')]), result([rule]), result([]), result([])]
    data = await api.design_map('private', session, user())
    assert data['knowledge_bases'] == [{'id': 'private', 'name': 'private'}]
    assert ['private'] in session.execute.call_args_list[2].args[0].compile().params.values()
    session.commit.assert_not_awaited()
