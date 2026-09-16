"""Build a reproducible browser fixture; optional --database reads existing data only."""
import argparse
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

from app.domain.design_map import build_design_map


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database')
    parser.add_argument('--output', default='artifacts/frontend/design-map-fixture.json')
    args = parser.parse_args()
    if args.database:
        with sqlite3.connect(f'file:{Path(args.database).resolve().as_posix()}?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            def rows(table, json_fields):
                items = []
                for row in conn.execute('SELECT * FROM ' + table):
                    item = dict(row)
                    for field in json_fields:
                        item[field] = json.loads(item[field]) if item.get(field) else None
                    items.append(NS(**item))
                return items
            units = rows('knowledge_unit', ['concepts', 'unit_meta'])
            docs = rows('document', ['index_meta'])
    else:
        docs = [NS(id='d1', filename='Receiver design.pdf', index_meta={}), NS(id='d2', filename='Receiver comparison.pdf', index_meta={})]
        units = []
        for number, (title, concepts, role, content) in enumerate([
            ('DFE 判决反馈均衡', ['DFE'], 'principle', '测试资料：DFE 使用已判决数据生成反馈信号。实际适用条件需结合文档核对。'),
            ('CTLE 连续时间均衡', ['CTLE'], 'principle', '测试资料：CTLE 为均衡模块中的一个候选技术，保留文档依据用于设计核对。'),
            ('SAR ADC 接收判决', ['SAR ADC'], 'principle', '测试资料：SAR ADC 的接收判决实现说明，原文应包含接口、采样和时序信息。'),
            ('DFE 适用约束', ['DFE'], 'constraint', '测试资料：DFE 的反馈时序必须依据目标速率核对。'),
            ('DFE 与 CTLE 对比', ['DFE', 'CTLE'], 'comparison', '测试资料：DFE 与 CTLE 的对比摘录；本示例不声称两种技术可以直接互换。'),
        ]):
            units.append(NS(id=f'u{number}', title=title, concepts=concepts, semantic_role=role, content=content,
                            lifecycle='AI_PROCESSED', unit_meta={}, document_id='d1' if number < 3 else 'd2', source_span='', source_page=2, source_chapter='II', source_section='Architecture'))
    data = build_design_map(units, docs)
    data['knowledge_bases'] = [{'id': 'fixture', 'name': '芯片设计知识库'}]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(data['summary']))


if __name__ == '__main__':
    main()
