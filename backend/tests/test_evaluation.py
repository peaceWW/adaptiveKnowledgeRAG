from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import importlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation.scoring import (aggregate, check_presentation, classify_question, matches, score_retrieval)
from app.storage.models import Base, GoldenCase, KnowledgeBase, KnowledgeStrategy, EvaluationRun
from app.storage.db import _migrate_schema
from app.api.schemas import GoldenCaseCreate

api = importlib.import_module('app.api.evaluation')


def test_question_intent_wins_over_supporting_roles():
    assert classify_question('如何解决 CDC 中的亚稳态问题？', ['definition', 'solution']) == '解决方案类'
    assert classify_question('为什么出现亚稳态', ['definition']) == '解释类'
    assert classify_question('对比两种方案', ['definition']) == '比较类'


def test_stable_ids_and_document_scoped_anchors():
    hit = {'id': 'u1', 'document_id': 'd1', 'title': 'Fig. 4 Receiver', 'anchor': 'fig:4', 'content': 'per-symbol bypass'}
    assert matches('id:u1', hit)
    assert matches('anchor:d1#Fig. 4', hit)
    assert not matches('anchor:d2#fig:4', hit)
    assert not matches('Fig. 4', hit)
    assert matches('keyword:per-symbol', hit)


def test_metrics_are_bounded_deduplicated_and_top10():
    case = {'required_knowledge': ['id:a', 'id:b', 'id:a'], 'optional_knowledge': ['id:c'], 'expected_roles': ['formula'], 'forbidden_knowledge': ['id:z']}
    hits = [{'id': 'a', 'semantic_role': 'principle'}, {'id': 'a'}, {'id': 'c'}]
    result = score_retrieval(case, {'ranked_hits': hits, 'hits': hits + [{'id': 'z'}], 'completeness': {'completeness_score': 1}})
    assert result['recall'] == .5
    assert result['precision'] == .2
    assert result['coverage'] == 0
    assert result['forbidden'] == ['id:z'] and result['pass'] is False
    assert score_retrieval(case, {'hits': [{'id': str(i)} for i in range(10)] + [{'id': 'a'}]})['mrr'] == 0
    assert score_retrieval({}, {'hits': []})['recall'] is None


def test_no_results_and_zero_are_distinct():
    assert api._kpis(None, None)['recall']['value'] is None
    assert api._kpis({'recall': 0}, None)['recall'] == {'value': 0, 'delta': None, 'up': False}
    assert aggregate([{'status': 'error'}])['recall'] is None
    assert aggregate([{'status': 'completed', 'recall': 0}])['recall'] == 0


def test_image_and_math_checks_do_not_invent_quality_scores():
    result = check_presentation({'evaluation_config': {'expected_kinds': ['figure', 'equation']}}, {'answer': '[[figure:unknown]]', 'citations': []})
    assert result['images'][0]['resolved'] is False
    assert result['images'][0]['available'] is None
    assert '回答未包含公式排版' in result['missing']
    assert check_presentation({}, {'answer': '$$x=1$$'})['has_math']


def test_case_validation():
    for payload in [{'question': '  '}, {'question': 'x', 'required_knowledge': ['anchor:fig4']}, {'question': 'x', 'required_knowledge': ['id:']}]:
        with pytest.raises(ValidationError):
            GoldenCaseCreate(**payload)


@pytest.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        strategy = KnowledgeStrategy(id='s', name='方案甲', knowledge_type='technical_concept', retrieval_policy={'solution': ['formula']}, completeness_policy={'minimum_coverage': .95, 'low_coverage': 'return_warning'})
        session.add(strategy)
        session.add(KnowledgeBase(id='kb', name='测试库', strategy_id='s'))
        session.add_all([GoldenCase(id=f'c{i}', dataset_name='tests', question=f'如何设计{i}', required_knowledge=['id:a'], kb_id='kb', evaluation_config={'answer_points': ['依据公式解释']}) for i in range(2)])
        await session.commit()
        yield session
    await engine.dispose()


USER = NS(id='admin', role='admin')


@pytest.mark.asyncio
async def test_empty_dataset_and_invalid_strategy_rejected(db):
    for request in [api.StartRun(dataset_name='empty'), api.StartRun(dataset_name='tests', strategy_id='missing')]:
        with pytest.raises(HTTPException):
            await api.run_evaluation(request, db, USER)


@pytest.mark.asyncio
async def test_durable_run_failure_isolation_idempotency_retry_and_snapshot(db, monkeypatch):
    run = await api.run_evaluation(api.StartRun(dataset_name='tests', strategy_id='s'), db, USER)
    assert run['status'] == 'queued' and run['config']['strategy']['id'] == 's'
    calls = []
    async def execute(case, config, session, user):
        calls.append(case['id'])
        if case['id'] == 'c0':
            raise RuntimeError('simulated model failure')
        return {**score_retrieval(case, {'hits': [{'id': 'a'}]}), 'answer': '实际答案', 'judge': {'status': 'disabled'}}
    monkeypatch.setattr(api, 'execute_case', execute)
    first = await api.step_run(run['id'], api.StepRequest(case_id='c0'), db, USER)
    assert first['status'] == 'queued' and first['metrics']['errors'] == 1
    await api.step_run(run['id'], api.StepRequest(case_id='c0'), db, USER)
    assert calls == ['c0']
    last = await api.step_run(run['id'], api.StepRequest(case_id='c1'), db, USER)
    assert last['status'] == 'completed_with_errors' and last['metrics']['recall'] == 1
    retry = await api.retry_run(run['id'], db, USER)
    assert retry['details'][0]['status'] == 'pending' and retry['details'][1]['answer'] == '实际答案'
    case = await db.get(GoldenCase, 'c0'); case.question = '修改过的问题'; await db.commit()
    assert retry['config']['cases'][0]['question'] != case.question
    assert last['config']['comparison_key'] == retry['config']['comparison_key']


@pytest.mark.asyncio
async def test_cancel_prevents_next_case_and_new_run_uses_new_dataset_hash(db, monkeypatch):
    run = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    await api.cancel_run(run['id'], db, USER)
    execute = AsyncMock(); monkeypatch.setattr(api, 'execute_case', execute)
    assert (await api.step_run(run['id'], api.StepRequest(case_id='c0'), db, USER))['status'] == 'cancelled'
    execute.assert_not_awaited()
    case = await db.get(GoldenCase, 'c0'); case.question = '另一问题'; await db.commit()
    new = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    assert new['config']['dataset_hash'] != run['config']['dataset_hash']


@pytest.mark.asyncio
async def test_judge_returns_unknown_for_missing_or_invalid_output():
    case = {'question': 'q', 'evaluation_config': {'answer_points': ['p']}}
    gateway = NS(chat_json=Mock(return_value={}))
    assert (await api.judge_answer(case, {}, gateway, True))['status'] == 'unavailable'
    gateway.chat_json.return_value = {'correctness': 1, 'groundedness': 1, 'completeness': 1, 'reason': '支持', 'evidence_ids': ['invented']}
    assert (await api.judge_answer(case, {}, gateway, True))['status'] == 'unavailable'
    gateway.chat_json.return_value['evidence_ids'] = []
    gateway.chat_json.return_value['groundedness'] = None
    result = await api.judge_answer(case, {}, gateway, True)
    assert result['correctness'] == 1 and result['groundedness'] is None
    assert (await api.judge_answer({'question': 'q'}, {}, gateway, True))['status'] == 'unconfigured'


@pytest.mark.asyncio
async def test_comparison_filters_incompatible_versions_and_incomplete_runs(db, monkeypatch):
    first = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    a = await db.get(EvaluationRun, first['id']); a.status = 'completed'; await db.commit()
    second = await api.run_evaluation(api.StartRun(dataset_name='tests', baseline_id=a.id), db, USER)
    b = await db.get(EvaluationRun, second['id']); b.status = 'completed'; await db.commit()
    assert api.comparable(a, b, True)
    b.config = {**b.config, 'comparison_key': 'changed'}; await db.commit()
    assert not api.comparable(a, b)
    with pytest.raises(HTTPException):
        await api.run_evaluation(api.StartRun(dataset_name='tests', baseline_id=b.id), db, USER)


@pytest.mark.asyncio
async def test_snapshot_drift_is_an_error_not_a_zero_score(db, monkeypatch):
    run = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    monkeypatch.setattr(api, 'runtime_snapshot', lambda: {'changed': True})
    result = await api.step_run(run['id'], api.StepRequest(case_id='c0'), db, USER)
    assert result['metrics']['recall'] is None
    assert '已变更' in result['details'][0]['error']


@pytest.mark.asyncio
async def test_strategy_changes_actual_plan(db):
    from app.retrieval.workflow import QueryWorkflow
    workflow = QueryWorkflow(db, NS(), NS())
    workflow.evaluation_strategy = {'id': 's', 'version': 'V2', 'knowledge_type': 'technical_concept', 'retrieval_policy': {'solution': ['formula']}, 'completeness_policy': {'minimum_coverage': .95, 'low_coverage': 'return_warning'}}
    result = await workflow.plan({'query': '如何计算', 'kb_id': 'kb', 'understanding': {'intent': 'solution', 'domain': 'semiconductor', 'topics': []}})
    assert result['plan']['required_roles'] == ['formula']
    assert result['plan']['completeness_threshold'] == .95
    assert result['plan']['secondary_retrieval'] is False


@pytest.mark.asyncio
async def test_migration_preserves_existing_rows_and_is_repeatable():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.execute(text('CREATE TABLE golden_case (id VARCHAR(36))'))
        await connection.execute(text('CREATE TABLE evaluation_run (id VARCHAR(36))'))
        await connection.execute(text("INSERT INTO evaluation_run (id) VALUES ('old')"))
        await connection.run_sync(_migrate_schema)
        await connection.run_sync(_migrate_schema)
        row = (await connection.execute(text('SELECT status, config, revision FROM evaluation_run'))).one()
        assert row == ('completed', None, 0)
    await engine.dispose()

@pytest.mark.asyncio
async def test_overview_keeps_no_data_unknown_and_classification_correct(db):
    result = await api.overview(dataset_name='tests', session=db, user=USER)
    assert result['latest'] is None and result['kpis']['recall']['value'] is None
    assert result['question_types'][0]['label'] == '解决方案类'
    assert result['trend'] == [] and result['strategy_compare'] == []


@pytest.mark.asyncio
async def test_completed_comparison_and_history_selection(db, monkeypatch):
    async def execute(case, config, session, user):
        return {**score_retrieval(case, {'hits': [{'id': 'a'}]}), 'answer': '依据', 'judge': {'status': 'disabled'}}
    monkeypatch.setattr(api, 'execute_case', execute)
    first = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    for case_id in ['c0', 'c1']:
        await api.step_run(first['id'], api.StepRequest(case_id=case_id), db, USER)
    second = await api.run_evaluation(api.StartRun(dataset_name='tests', baseline_id=first['id'], strategy_id='s'), db, USER)
    for case_id in ['c0', 'c1']:
        await api.step_run(second['id'], api.StepRequest(case_id=case_id), db, USER)
    result = await api.overview(dataset_name='tests', run_id=second['id'], session=db, user=USER)
    assert result['comparison']['baseline_id'] == first['id']
    assert result['comparison']['deltas']['recall']['delta'] == 0
    assert len(result['strategy_compare']) == 2
    historical = await api.overview(dataset_name='tests', run_id=first['id'], session=db, user=USER)
    assert historical['latest']['id'] == first['id']


@pytest.mark.asyncio
async def test_cancel_during_step_is_not_overwritten(db, monkeypatch):
    async def execute(case, config, session, user):
        await api.cancel_run(run['id'], session, user)
        return {'recall': 0, 'precision': 0, 'mrr': 0, 'coverage': None, 'pass': False}
    monkeypatch.setattr(api, 'execute_case', execute)
    run = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    result = await api.step_run(run['id'], api.StepRequest(case_id='c0'), db, USER)
    assert result['status'] == 'cancelled'
    assert result['details'][0]['status'] == 'completed'
    assert result['details'][1]['status'] == 'pending'


@pytest.mark.asyncio
async def test_expired_cancelled_step_can_be_retried(db):
    run = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    row = await db.get(EvaluationRun, run['id'])
    row.status = 'cancelled'
    row.details = [{**row.details[0], 'status': 'running'}, row.details[1]]
    row.config = {**row.config, 'step_started': 1}
    await db.commit()
    recovered = await api.read_run(row.id, db, USER)
    assert recovered['status'] == 'cancelled' and recovered['metrics']['errors'] == 1
    retry = await api.retry_run(row.id, db, USER)
    assert all(d['status'] == 'pending' for d in retry['details'])


@pytest.mark.asyncio
async def test_run_owner_enforced(db):
    run = await api.run_evaluation(api.StartRun(dataset_name='tests'), db, USER)
    with pytest.raises(HTTPException) as error:
        await api.read_run(run['id'], db, NS(id='other', role='end_user'))
    assert error.value.status_code == 403
