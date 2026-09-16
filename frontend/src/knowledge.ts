export const extractionCategories = [
  { key: 'text', policy_key: 'text', label: '提取文本', description: '按知识类别组织概念、原理、约束、示例等内容' },
  { key: 'equation', policy_key: 'formulas', label: '提取公式', description: '公式独立成知识点，保留编号、原稿截图与可识别表达式' },
  { key: 'figure', policy_key: 'images', label: '提取图片', description: '按图独立提取原稿裁图、图注与来源页，包括无图注的嵌入图片' },
  { key: 'table', policy_key: 'tables', label: '提取表格', description: '保留表头、单元格和表格截图，避免与正文混合切分' },
  { key: 'citation', policy_key: 'references', label: '参考文献', description: '按引用条目拆分，保留引用编号与出处' },
];
export const defaultExtractionPolicy = () => ({ text: true, formulas: true, images: true, tables: true, references: true,
  chunk_size: 1200, chunk_overlap: 100, formula_mode: 'source', image_mode: 'source', table_mode: 'source' });
export const chunkLabels: Record<string, string> = { semantic_unit: '按语义拆分', section: '按章节拆分', fixed_token: '按固定长度拆分' };
export const strategyLabels: Record<string, string> = { 'Technical Knowledge V1': '技术知识策略 V1', 'Incident Case V1': '故障案例策略 V1', 'API Document V1': '接口文档策略 V1' };
export function strategyLabel(name = '') { return strategyLabels[name] || name; }
export const roleLabels: Record<string, string> = {
  definition: '概念定义', explanation: '解释说明', principle: '技术原理', classification: '分类体系', related_concept: '相关概念',
  background: '背景知识', summary: '摘要总结', constraint: '约束条件', parameter: '参数指标', rule: '设计规则', exception: '例外情况',
  formula: '公式', requirement: '规格需求', obligation: '法定义务', prohibition: '禁止事项', clause: '条款', example: '应用示例',
  reference: '参考文献', solution: '解决方案', procedure: '操作流程', step: '执行步骤', actor: '责任角色', best_practice: '最佳实践',
  comparison: '方案对比', root_cause: '根因分析', symptom: '故障现象', prevention: '预防措施', impact: '影响范围', environment: '运行环境',
  api_input: '接口入参', api_output: '接口出参', error_code: '错误码', metric: '性能指标', limitation: '能力边界', interface: '接口说明',
  sla: '服务时效', checklist: '检查清单', warning: '风险警告', assumption: '前提假设', scope: '适用范围', timeline: '时间线', decision: '决策记录', consequence: '后果影响',
};
export function extractionKind(unit: any): string {
  if (unit.extraction_kind) return unit.extraction_kind;
  const kind = unit.unit_meta?.kind;
  if (['equation', 'figure', 'table', 'citation'].includes(kind)) return kind;
  if (unit.semantic_role === 'formula') return 'equation';
  if (unit.semantic_role === 'reference') return 'citation';
  return 'text';
}
