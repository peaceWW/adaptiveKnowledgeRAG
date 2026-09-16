"""Read-only, evidence-backed projection of extracted units onto chip-design tasks.

The taxonomy describes navigation, never invents available implementations or
replacement claims. Every populated technology node refers to stored units.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from app.domain.enums import RETRIEVAL_LIFECYCLES
from app.storage.paths import attach_image_refs

# Stable keys keep selections/links valid as additional documents are ingested.
MODULES = [
    ('tx-linear', '发射端线性化', ['发射端线性化', '预加重', '去加重', 'pre-emphasis', 'de-emphasis', 'predistortion'], [
        ('pre-emphasis', '预加重', ['pre-emphasis', '预加重']),
        ('de-emphasis', '去加重', ['de-emphasis', '去加重']),
        ('predistortion', '预失真', ['predistortion', '预失真']),
    ]),
    ('tx-output', '发射端输出', ['发射端输出', '发射驱动', 'output driver', 'TX driver', 'transmitter driver', '电流模', '电压模'], [
        ('cml', '电流模驱动 CML', ['CML', 'current-mode driver', '电流模驱动']),
        ('sst', '源端串联终端 SST', ['SST', 'source-series terminated']),
        ('voltage-driver', '电压模驱动', ['voltage-mode driver', '电压模驱动']),
    ]),
    ('equalization', '均衡与反馈', ['equalization', 'equalizer', '均衡', 'FFE', 'DFE', 'CTLE'], [
        ('ctle', '连续时间线性均衡 CTLE', ['CTLE', 'continuous-time linear equalizer', '连续时间线性均衡']),
        ('analog-ffe', '模拟前馈均衡 FFE', ['analog FFE', 'analog feed-forward', '模拟前馈均衡', '模拟FFE']),
        ('digital-ffe', '数字前馈均衡 FFE', ['digital FFE', 'digital feed-forward', '数字前馈均衡', '数字FFE']),
        ('ffe', '前馈均衡 FFE', ['FFE', 'feed-forward equalizer', '前馈均衡']),
        ('dfe', '判决反馈均衡 DFE', ['DFE', 'decision-feedback', '判决反馈均衡', '决策反馈均衡']),
    ]),
    ('rx-decision', '接收判决链', ['ADC', 'SAR', '接收判决', '模数转换', '比较器', '采样保持', 'slicer', 'comparator'], [
        ('sar', '逐次逼近 SAR ADC', ['SAR', '逐次逼近']),
        ('flash', 'Flash ADC', ['flash ADC', 'flash converter', '闪速ADC', '全并行ADC']),
        ('pipeline', '流水线 ADC', ['pipeline ADC', 'pipelined ADC', '流水线ADC', '流水线 ADC']),
        ('ti-adc', '时间交织 ADC', ['TI-ADC', 'time-interleaved', '时间交织', '时域交织']),
        ('slicer', '判决器 / Slicer', ['slicer', '判决器']),
        ('comparator', '比较器', ['comparator', '比较器']),
    ]),
    ('datapath', '数据路径与速率变换', ['数据路径', '速率变换', '串并转换', '并串转换', 'serializer', 'deserializer', 'MUX', 'DEMUX', 'gearbox'], [
        ('serializer', '串行化器', ['serializer', '并串转换']),
        ('deserializer', '解串器', ['deserializer', '串并转换']),
        ('gearbox', 'Gearbox 速率变换', ['gearbox']),
        ('mux', '多路复用 MUX', ['MUX', 'multiplexer']),
        ('demux', '解复用 DEMUX', ['DEMUX', 'demultiplexer']),
    ]),
    ('clock', '时钟与相位', ['时钟', '相位', 'clock', 'phase', 'CDR', 'PLL', 'DLL'], [
        ('cdr', '时钟数据恢复 CDR', ['CDR', 'clock and data recovery', '时钟数据恢复']),
        ('pll', '锁相环 PLL', ['PLL', 'phase-locked loop', '锁相环']),
        ('dll', '延迟锁定环 DLL', ['DLL', 'delay-locked loop', '延迟锁定环']),
        ('phase-interpolator', '相位插值器', ['phase interpolator', '相位插值']),
    ]),
    ('summing', '求和与输出', ['求和', 'summing', 'summer', '加法器', 'adder'], [
        ('current-summer', '电流求和', ['current-mode summer', 'current summing', '电流求和']),
        ('voltage-summer', '电压求和', ['voltage-mode summer', 'voltage summing', '电压求和']),
        ('adder', '数字加法器', ['digital adder', '数字加法器']),
    ]),
    ('cdc', '跨时钟域与复位', ['CDC', '跨时钟域', 'metastability', '亚稳态', 'synchronizer', '同步器', 'Async FIFO', '异步FIFO', '异步 FIFO'], [
        ('synchronizer', '同步器', ['synchronizer', '同步器']),
        ('async-fifo', '异步 FIFO', ['Async FIFO', 'asynchronous FIFO', '异步FIFO', '异步 FIFO']),
        ('handshake', '握手同步', ['handshake', '握手同步']),
        ('gray-code', '格雷码', ['Gray Code', '格雷码']),
    ]),
    ('power', '电源与偏置', ['电源管理', '偏置', 'bias', 'LDO', 'bandgap'], [
        ('ldo', '低压差稳压器 LDO', ['LDO', '低压差稳压']),
        ('bandgap', '带隙基准', ['bandgap', '带隙基准']),
        ('bias', '偏置电路', ['bias circuit', '偏置电路']),
    ]),
]
FACETS = [
    ('concepts', '概念与原理', {'definition', 'explanation', 'principle', 'classification', 'formula', 'related_concept'}),
    ('metrics', '性能指标', {'metric', 'parameter'}),
    ('constraints', '设计约束与风险', {'constraint', 'rule', 'limitation', 'exception', 'warning', 'requirement', 'assumption', 'root_cause', 'symptom'}),
    ('comparisons', '方案对比', {'comparison'}),
]


def _normal(text):
    return re.sub(r'[\s_‐‑–—-]+', ' ', str(text or '')).casefold()


def matches(text, aliases):
    text = _normal(text)
    for alias in aliases:
        value = _normal(alias)
        left = r'(?<![a-z0-9])' if value and value[0].isascii() and value[0].isalnum() else ''
        right = r'(?![a-z0-9])' if value and value[-1].isascii() and value[-1].isalnum() else ''
        if value and re.search(left + re.escape(value) + right, text):
            return True
    return False


def _key(value):
    return hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]


def build_design_map(units, documents):
    documents = {doc.id: doc for doc in documents}
    units = [u for u in units if u.lifecycle in RETRIEVAL_LIFECYCLES and not (u.unit_meta or {}).get('stub')]
    nodes, evidence, memberships = {}, {}, defaultdict(set)

    def add(key, name, kind, parent=None, aliases=None):
        if key not in nodes:
            nodes[key] = {'id': key, 'name': name, 'kind': kind, 'parent_id': parent, 'aliases': aliases or [], 'children': [], 'evidence_ids': []}
            if parent:
                nodes[parent]['children'].append(key)
        return key

    add('chip', '芯片设计', 'root')
    add('architecture', '架构', 'category', 'chip')
    add('ip', 'IP 架构', 'category', 'architecture')
    for key, label in [('rx', 'RX · 接收端'), ('rxtx', 'RX & TX · 收发一体'), ('tx', 'TX · 发射端')]:
        add('ip:' + key, label, 'ip', 'ip')
    add('modules', '模块架构', 'category', 'architecture')
    for key, name, aliases, technologies in MODULES:
        add('module:' + key, name, 'module', 'modules', aliases)
    for key, label, _ in FACETS:
        add(key, label, 'category', 'chip')
    add('unmapped', '待归类知识', 'category', 'chip')

    for unit in sorted(units, key=lambda u: (u.title or '', u.id)):
        doc = documents.get(unit.document_id)
        meta = attach_image_refs(unit.document_id, unit.unit_meta)
        evidence[unit.id] = {
            'id': unit.id, 'title': unit.title, 'content': (unit.content or '')[:6000],
            'original': (unit.source_span or '')[:6000], 'role': unit.semantic_role,
            'lifecycle': unit.lifecycle, 'document_id': unit.document_id,
            'document_title': ((doc.index_meta or {}).get('title') or doc.filename) if doc else '未关联文档',
            'filename': doc.filename if doc else '', 'page': unit.source_page,
            'chapter': unit.source_chapter, 'section': unit.source_section,
            'image_key': meta.get('image_key', ''), 'image_url': meta.get('image_url', ''),
            'kind': meta.get('kind') or '', 'latex': meta.get('latex') or '',
        }
        focal = ' '.join([
            unit.title or '',
            *[str(c) for c in unit.concepts or []],
            str(meta.get('engineering_topic') or ''),
        ])
        full = focal + '\n' + (unit.content or '')
        assigned = False
        for module_key, name, aliases, technologies in MODULES:
            if not matches(full, aliases):
                continue
            assigned = True
            module_id = 'module:' + module_key
            memberships[module_id].add(unit.id)
            # A content-only mention is supporting material, not a claimed implementation.
            found = [(key, title, names) for key, title, names in technologies if matches(focal, names)]
            if any(key in {'analog-ffe', 'digital-ffe'} for key, _, _ in found):
                found = [t for t in found if t[0] != 'ffe']
            if not found and unit.semantic_role in {'solution', 'best_practice', 'procedure', 'interface'} and matches(focal, aliases):
                found = [('source-' + _key(unit.title), unit.title, [])]
            for key, title, names in found:
                tid = add(module_id + ':' + key, title, 'technology', module_id, names)
                memberships[tid].add(unit.id)

        doc_title = evidence[unit.id]['document_title']
        # Classify the IP by the document's own title, not a mention of TX inside an RX paper.
        ip_rx = matches(doc_title, ['RX', 'receiver', '接收机', '接收器'])
        ip_tx = matches(doc_title, ['TX', 'transmitter', '发射机', '发射器'])
        ip_both = matches(doc_title, ['transceiver', '收发器', '收发机', 'RX&TX', 'RX & TX']) or (ip_rx and ip_tx)
        if ip_both or ip_rx or ip_tx:
            parent = 'ip:rxtx' if ip_both else 'ip:rx' if ip_rx else 'ip:tx'
            did = add(parent + ':' + str(unit.document_id), doc_title, 'document', parent)
            memberships[did].add(unit.id)
        for facet, _, roles in FACETS:
            if unit.semantic_role in roles:
                # Deduplicate concepts across documents; raw unit references stay in the evidence panel.
                concepts = [
                    str(c).strip()
                    for c in unit.concepts or []
                    if str(c).strip() and not re.match(r'(?i)^(fig\.|eq\.)', str(c).strip())
                ]
                topic = concepts[0] if facet == 'concepts' and concepts else unit.title
                nid = add(facet + ':' + _key(_normal(topic)), topic, 'topic', facet)
                memberships[nid].add(unit.id)
                assigned = True
        if not assigned:
            nid = add('unmapped:' + unit.id, unit.title, 'topic', 'unmapped')
            memberships[nid].add(unit.id)

    def aggregate(key):
        node = nodes[key]
        ids = set(memberships[key])
        tech_ids = set()
        for child in node['children']:
            child_ids, child_techs = aggregate(child)
            ids.update(child_ids)
            tech_ids.update(child_techs)
        if node['kind'] == 'technology':
            tech_ids.add(key)
        node['evidence_ids'] = sorted(ids)
        node['unit_count'] = len(ids)
        node['document_count'] = len({evidence[i]['document_id'] for i in ids if evidence[i]['document_id']})
        node['technology_ids'] = sorted(tech_ids)
        return ids, tech_ids

    aggregate('chip')
    for key, node in nodes.items():
        node['path'] = [key]
        parent = node['parent_id']
        while parent:
            node['path'].insert(0, parent)
            parent = nodes[parent]['parent_id']
    return {
        'root_id': 'chip', 'nodes': list(nodes.values()), 'evidence': evidence,
        'summary': {'units': len(evidence), 'documents': nodes['chip']['document_count'],
                    'modules': sum(n['kind'] == 'module' and n['unit_count'] > 0 for n in nodes.values()),
                    'technologies': sum(n['kind'] == 'technology' for n in nodes.values()),
                    'unmapped': nodes['unmapped']['unit_count']},
        'method': '按模块术语和已抽取知识自动归类；同模块技术是候选方案，不代表可直接替换。请结合接口、速率、工艺、功耗和时序核对原文。',
    }
