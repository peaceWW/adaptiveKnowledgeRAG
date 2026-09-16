from types import SimpleNamespace as NS

from app.domain.design_map import build_design_map, matches


def unit(id='u1', **kwargs):
    data = dict(id=id, title='SAR ADC', content='SAR ADC 接收判决链', concepts=['SAR ADC'], semantic_role='principle', lifecycle='AI_PROCESSED', unit_meta={}, document_id='d1', source_span='', source_page=2, source_chapter='II', source_section='Architecture')
    data.update(kwargs)
    return NS(**data)


def doc(id='d1', **kwargs):
    data = dict(id=id, filename='receiver.pdf', index_meta={})
    data.update(kwargs)
    return NS(**data)


def index(data):
    return {n['id']: n for n in data['nodes']}


def test_cross_document_technology_merge_and_provenance():
    result = build_design_map([unit(), unit('u2', document_id='d2', title='SAR 功耗', semantic_role='metric', content='实测 SAR ADC 功耗为 12 mW。')], [doc(), doc('d2')])
    node = index(result)['module:rx-decision:sar']
    assert node['document_count'] == 2
    assert node['evidence_ids'] == ['u1', 'u2']
    assert result['summary']['units'] == 2  # tree cross-links never inflate totals
    assert result['evidence']['u2']['content'] == '实测 SAR ADC 功耗为 12 mW。'
    assert result['evidence']['u2']['page'] == 2


def test_no_invented_technology_from_framework_or_incidental_mention():
    result = build_design_map([unit(title='通用讨论', concepts=[], content='后文提到 SAR ADC，但此段没有描述实现。')], [doc()])
    nodes = index(result)
    assert nodes['module:rx-decision']['unit_count'] == 1
    assert nodes['module:rx-decision']['technology_ids'] == []
    assert nodes['module:tx-output']['unit_count'] == 0
    assert result['summary']['technologies'] == 0


def test_match_boundaries_and_ffe_specificity():
    assert not matches('offset differs from coefficient', ['FFE'])
    assert not matches('DEMUX', ['MUX'])
    assert not matches('deserializer', ['serializer'])
    assert matches('time‐interleaved', ['time-interleaved'])
    result = build_design_map([unit(title='模拟前馈均衡 FFE', concepts=['analog FFE'], content='模拟前馈均衡 FFE')], [doc()])
    nodes = index(result)
    assert 'module:equalization:analog-ffe' in nodes
    assert 'module:equalization:ffe' not in nodes


def test_retired_draft_and_stub_units_are_not_offered():
    result = build_design_map([unit('a', lifecycle='DEPRECATED'), unit('b', lifecycle='DRAFT'), unit('c', unit_meta={'stub': True})], [doc()])
    assert result['summary']['units'] == 0
    assert result['summary']['technologies'] == 0


def test_rx_document_not_classified_as_tx_due_to_content_mention():
    result = build_design_map([unit(content='RX includes ADC and is driven by TX')], [doc()])
    nodes = index(result)
    assert nodes['ip:rx']['document_count'] == 1
    assert nodes['ip:tx']['document_count'] == 0


def test_unmapped_units_remain_discoverable_and_ids_stable():
    a = unit(title='专用工艺记录', concepts=[], content='独立实验记录', semantic_role='background')
    data = build_design_map([a], [doc()])
    assert index(data)['unmapped']['evidence_ids'] == ['u1']
    assert index(data)['chip']['unit_count'] == 1
    assert index(data).keys() == index(build_design_map([a], [doc()])).keys()


def test_unknown_named_solution_is_preserved_under_module():
    result = build_design_map([unit(title='自适应 DFE 新方案', concepts=['DFE'], semantic_role='solution'), unit('u2', title='分段求和实现', concepts=[], content='分段求和实现', semantic_role='solution')], [doc()])
    nodes = index(result)
    assert nodes['module:equalization:dfe']['evidence_ids'] == ['u1']
    assert any(n['name'] == '分段求和实现' and n['kind'] == 'technology' for n in nodes.values())
