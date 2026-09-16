<template>
  <div class="eval-page">
    <header class="hero"><div><h2>评估中心</h2><p>用固定问题检查检索与回答，比较每次调整带来的变化。</p></div><a-space><a-dropdown :disabled="!selected"><a-button :disabled="!selected">导出报告</a-button><template #overlay><a-menu @click="({ key }: any) => exportReport(key)"><a-menu-item key="json">完整报告 JSON</a-menu-item><a-menu-item key="csv">逐题结果 CSV</a-menu-item></a-menu></template></a-dropdown><a-button type="primary" :disabled="!dataset || !golden.length || driving || active" @click="startRun">开始评估</a-button></a-space></header>
    <div class="filters card">
      <label>评估集<a-select v-model:value="dataset" :disabled="driving" placeholder="先新增评估用例" @change="changeDataset"><a-select-option v-for="name in datasets" :key="name">{{ name }}</a-select-option></a-select></label>
      <label>执行策略<a-select v-model:value="strategyId" allow-clear :disabled="driving" placeholder="知识库默认策略"><a-select-option v-for="s in strategies" :key="s.id">{{ s.name }} · {{ s.version }}</a-select-option></a-select></label>
      <label>对比基准<a-select v-model:value="baselineId" allow-clear :disabled="driving" placeholder="可选，需相同评估条件"><a-select-option v-for="r in completedRuns" :key="r.id">{{ r.strategy_name }} · {{ time(r.created_at) }}</a-select-option></a-select></label>
      <a-checkbox v-model:checked="judgeAnswers" :disabled="driving">启用模型答案评审</a-checkbox>
    </div>
    <p class="hint">策略会影响知识类型、检索角色与完整性检查；不重新抽取文档。模型评审需要参考答案或评分要点，并会增加调用耗时。</p>
    <a-alert v-if="loadError" type="error" show-icon :message="loadError" />
    <a-alert v-if="!golden.length && !loading" type="info" show-icon message="尚无评估用例，请在实验管理中新增问题并标注必需证据。" />
    <div v-if="selected" class="run-banner card">
      <div class="run-heading"><b>{{ selected.strategy_name }} · {{ statusText(selected.status) }}</b><span>{{ time(selected.created_at) }}</span><a-space><a-button v-if="selected.status === 'queued' && !driving" @click="drive(selected)">继续评估</a-button><a-button v-if="active" danger @click="cancelRun">停止后续题目</a-button><a-button v-if="canRetry && !driving" @click="retryRun">重试失败／未完成题</a-button></a-space></div>
      <a-progress :percent="progress" :status="selected.status === 'completed_with_errors' ? 'exception' : undefined" />
      <small>已处理 {{ processed }} / {{ selected.details.length }} 题 · 执行失败 {{ selected.metrics.errors || 0 }} 题 · 检索可评分 {{ selected.metrics.scored_cases ?? '—' }} 题 · 模型已评审 {{ selected.metrics.judged ?? '—' }} 题</small><p class="hint">分数取成功执行且具有对应标注的题目平均值；失败和未标注题不计为 0 分，请结合处理数量判断结果。</p>
      <p v-if="active" class="hint">{{ currentQuestion ? `正在评估：${currentQuestion}` : '待执行下一题' }}。停止会在当前题结束后生效；离开页面后可在实验记录中继续。</p>
      <a-alert v-if="selected.legacy" type="warning" message="这是旧版实验，评分口径不同，仅供查看，不参与新版本指标与对比。" />
    </div>
    <a-tabs v-model:activeKey="tab"><a-tab-pane key="retrieval" tab="检索评估" /><a-tab-pane key="answer" tab="答案评估" /><a-tab-pane key="compare" tab="策略对比" /><a-tab-pane key="experiments" tab="实验管理" /></a-tabs>
    <div v-if="tab === 'retrieval'">
      <div class="kpi-grid"><div v-for="metric in retrievalMetrics" :key="metric.key" class="card kpi"><span>{{ metric.label }}</span><b>{{ metricValue(metric.key) }}</b><small>{{ metric.help }}</small></div></div>
      <a-alert v-if="!selected" type="info" message="尚未评估，指标显示为 —，不代表得分为 0。" />
      <div class="chart-row">
        <div class="card"><h3>同条件指标趋势</h3><p class="hint">仅纳入相同数据、模型、提示词与策略配置的完整实验。</p><div v-if="trend.length" class="trend"><svg viewBox="0 0 560 190" role="img" aria-label="召回率、精确率与角色覆盖率趋势"><g v-for="level in [0, 50, 100]" :key="level"><line x1="35" :y1="160 - level * 1.4" x2="540" :y2="160 - level * 1.4" stroke="#e5eaf2" /><text x="0" :y="164 - level * 1.4">{{ level }}%</text></g><g v-for="line in trendLines" :key="line.key"><polyline :points="line.points" fill="none" :stroke="line.color" stroke-width="2" /><circle v-for="point in line.dots" :key="point.id" :cx="point.x" :cy="point.y" r="4" :fill="line.color"><title>{{ point.label }}</title></circle></g></svg><div class="legend"><span>🟣 召回率</span><span>🔵 精确率</span><span>🟢 角色覆盖率</span></div></div><a-empty v-else description="完成同条件评估后显示趋势" /></div>
        <div class="card"><h3>评估集问题分布</h3><b>{{ golden.length }} 道题</b><div v-for="item in overview.question_types || []" :key="item.label" class="type-row"><span>{{ item.label }}</span><a-progress :percent="item.percent" :stroke-color="item.color" size="small" /></div></div>
      </div>
      <div class="card"><h3>逐题检索结果</h3><a-table :columns="detailCols" :data-source="selected?.details || []" row-key="case_id" :scroll="{ x: 780 }" size="small"><template #bodyCell="{ column, record }"><template v-if="column.key === 'status'">{{ statusText(record.status) }}</template><template v-else-if="column.key === 'pass'">{{ record.pass == null ? '未评分' : record.pass ? '通过' : '未通过' }}</template><a-button v-else-if="column.key === 'action'" type="link" @click="detail = record">查看详情</a-button></template></a-table></div>
    </div>
    <div v-else-if="tab === 'answer'">
      <a-alert type="info" show-icon message="答案评分由模型依据参考答案与检索证据评审，需人工复核；有引用不等于回答正确。图片检查验证引用与文件可读取性，公式检查验证排版标记。" />
      <div class="kpi-grid answer-kpis"><div v-for="metric in answerMetrics" :key="metric.key" class="card kpi"><span>{{ metric.label }}</span><b>{{ metricValue(metric.key) }}</b><small>{{ metric.help }}</small></div></div>
      <div class="card"><a-table :columns="answerCols" :data-source="selected?.details || []" row-key="case_id" :scroll="{ x: 720 }" size="small"><template #bodyCell="{ column, record }"><template v-if="column.key === 'judge'">{{ judgeText(record.judge?.status) }}</template><template v-else-if="column.key === 'media'">{{ mediaText(record) }}</template><a-button v-else-if="column.key === 'action'" type="link" @click="detail = record">复盘回答</a-button></template></a-table></div>
    </div>
    <div v-else-if="tab === 'compare'">
      <a-alert type="info" show-icon message="仅比较相同评估集快照、知识库内容、模型、提示词和评分版本的完整实验；每种策略配置取最新结果。" />
      <div class="card"><a-table :columns="compareCols" :data-source="overview.strategy_compare || []" row-key="id" :scroll="{ x: 780 }" size="small" /></div>
      <div v-if="overview.comparison" class="card"><h3>相对选定基准的变化</h3><div class="kpi-grid"><div v-for="metric in retrievalMetrics" :key="metric.key"><span>{{ metric.label }}</span><b class="delta">{{ deltaText(overview.comparison.deltas[metric.key], metric.key === 'mrr') }}</b></div></div><h3>召回率下降的问题</h3><a-table :columns="regressionCols" :data-source="overview.comparison.regressions" row-key="case_id" size="small" /></div>
      <p v-else class="hint">开始评估前可选择基准实验，完成后查看变化与退步问题。不满足比较条件时会说明原因。</p>
    </div>
    <div v-else>
      <div class="card"><div class="card-head"><h3>评估用例</h3><a-button type="primary" @click="editCase()">新增用例</a-button></div><a-table :columns="goldenCols" :data-source="golden" row-key="id" :scroll="{ x: 700 }" size="small"><template #bodyCell="{ column, record }"><a-space v-if="column.key === 'action'"><a-button type="link" @click="editCase(record)">编辑</a-button><a-popconfirm title="删除此用例？已保存的实验快照将保留。" @confirm="deleteCase(record.id)"><a-button type="link" danger>删除</a-button></a-popconfirm></a-space></template></a-table></div>
      <div class="card"><h3>实验记录</h3><a-table :columns="runCols" :data-source="overview.runs || []" row-key="id" :scroll="{ x: 820 }" size="small"><template #bodyCell="{ column, record }"><template v-if="column.key === 'status'">{{ record.legacy ? '旧版记录' : statusText(record.status) }}</template><a-button v-else-if="column.key === 'action'" type="link" :disabled="driving" @click="selectRun(record)">查看实验</a-button></template></a-table></div>
    </div>
    <a-modal v-model:open="showCase" :title="editingId ? '编辑评估用例' : '新增评估用例'" :width="800" :confirm-loading="saving" ok-text="保存" cancel-text="取消" @ok="saveCase">
      <a-form layout="vertical"><div class="form-grid"><a-form-item label="评估集" required><a-input v-model:value="caseForm.dataset_name" /></a-form-item><a-form-item label="知识库" required><a-select v-model:value="caseForm.kb_id" @change="loadUnits"><a-select-option v-for="kb in kbs" :key="kb.id">{{ kb.name }}</a-select-option></a-select></a-form-item></div>
        <a-form-item label="问题" required><a-textarea v-model:value="caseForm.question" :rows="2" /></a-form-item>
        <a-form-item label="从知识库选择必需证据"><a-select mode="multiple" v-model:value="selectedUnitIds" show-search :filter-option="filterUnit" :options="unitOptions" placeholder="按标题搜索知识点、图片或公式" /></a-form-item>
        <a-form-item label="其他必需证据（每行一项）"><a-textarea v-model:value="caseForm.required" :rows="3" placeholder="id:知识单元ID&#10;anchor:文档ID#fig:4&#10;keyword:必须匹配的内容&#10;或完整知识点标题" /><small>优先使用上方知识单元选择；旧标题仍可兼容。至少标注一项必需证据。</small></a-form-item>
        <div class="form-grid"><a-form-item label="可选证据（每行一项）"><a-textarea v-model:value="caseForm.optional" /></a-form-item><a-form-item label="禁止命中的证据（每行一项）"><a-textarea v-model:value="caseForm.forbidden" /></a-form-item></div>
        <a-form-item label="预期知识角色（每行一项，用于覆盖率）"><a-textarea v-model:value="caseForm.roles" placeholder="principle&#10;formula&#10;constraint" /></a-form-item>
        <a-form-item label="回答应包含的内容"><a-checkbox-group v-model:value="caseForm.expected_kinds" :options="kindOptions" /></a-form-item>
        <a-form-item label="参考答案"><a-textarea v-model:value="caseForm.reference_answer" :rows="3" /></a-form-item><a-form-item label="评分要点（每行一项）"><a-textarea v-model:value="caseForm.answer_points" :rows="3" placeholder="列出应解释的原理、约束、公式符号与图中模块关系" /></a-form-item>
      </a-form>
    </a-modal>
    <a-drawer :open="!!detail" title="逐题复盘" width="min(100vw, 940px)" @close="detail = undefined">
      <template v-if="detail"><h3>{{ detail.question }}</h3><a-alert v-if="detail.error" type="error" :message="detail.error" /><p>执行状态：{{ statusText(detail.status) }} · 耗时 {{ ((detail.elapsed_ms || 0) / 1000).toFixed(1) }} 秒</p>
        <div class="review-grid"><div class="card"><h4>已命中必需证据</h4><ul><li v-for="item in detail.matched || []" :key="item">{{ item }}</li></ul><span v-if="!detail.matched?.length">暂无</span></div><div class="card"><h4>缺失／禁止命中</h4><ul><li v-for="item in detail.missing || []" :key="item">缺失：{{ item }}</li><li v-for="item in detail.forbidden || []" :key="item">禁止：{{ item }}</li><li v-for="item in detail.missing_roles || []" :key="item">缺少角色：{{ item }}</li></ul></div></div>
        <p v-for="warning in detail.warnings || []" :key="warning" class="hint">{{ warning }}</p>
        <h4>答案评审 · {{ judgeText(detail.judge?.status) }}</h4><p>{{ detail.judge?.reason || '尚未评审' }}</p><p>正确性 {{ pct(detail.judge?.correctness) }} · 依据支持度 {{ pct(detail.judge?.groundedness) }} · 完整性 {{ pct(detail.judge?.completeness) }}</p>
        <h4>图片与公式检查</h4><p>{{ mediaText(detail) }}</p><ul><li v-for="img in detail.presentation?.images || []" :key="img.id">{{ img.id }}：引用{{ img.resolved ? '有效' : '无效' }}，文件{{ img.available == null ? '未验证' : img.available ? '可读取' : '不可读取' }}</li><li v-for="item in detail.presentation?.missing || []" :key="item">{{ item }}</li></ul><p class="hint">{{ detail.presentation?.scope }}</p>
        <h4>实际回答</h4><AnswerContent v-if="detail.answer" :text="detail.answer" :citations="detail.citations || []" @source="source = $event" /><a-empty v-else description="尚无回答" />
        <details><summary>参考答案与评分要点</summary><p class="prewrap">{{ detail.expected?.evaluation_config?.reference_answer || '未填写' }}</p><ul><li v-for="p in detail.expected?.evaluation_config?.answer_points || []" :key="p">{{ p }}</li></ul></details>
        <details><summary>实际检索结果（重排顺序）</summary><ol><li v-for="hit in detail.hits || []" :key="hit.id"><b>{{ hit.title }}</b> · {{ hit.id }}<p>{{ hit.content }}</p></li></ol></details>
        <details><summary>本题实际执行策略</summary><pre>{{ JSON.stringify(detail.plan || {}, null, 2) }}</pre></details>
      </template>
    </a-drawer>
    <a-modal :open="!!source" title="引用证据" :footer="null" @cancel="source = undefined"><template v-if="source"><h3>{{ source.title }}</h3><p>{{ source.document_title }} · 第 {{ source.page || '未知' }} 页</p><div v-html="renderAnswer(source.content || '')"></div><DocumentAsset v-if="source.image_key || source.image_url" :document-id="source.document_id || ''" :image-key="source.image_key" :image-url="source.image_key ? undefined : source.image_url" :alt="source.title" :show-url="false" /></template></a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { message } from 'ant-design-vue';
import { api } from '../api';
import AnswerContent from '../components/AnswerContent.vue';
import DocumentAsset from '../components/DocumentAsset.vue';
import { renderAnswer } from '../answer';
const tab = ref('retrieval'), dataset = ref<string>(), datasets = ref<string[]>([]), strategies = ref<any[]>([]), kbs = ref<any[]>([]), golden = ref<any[]>([]);
const strategyId = ref<string>(), baselineId = ref<string>(), judgeAnswers = ref(false), overview = ref<any>({}), selected = ref<any>(), detail = ref<any>(), source = ref<any>();
const loading = ref(false), driving = ref(false), loadError = ref(''), showCase = ref(false), saving = ref(false), editingId = ref<string>();
const unitOptions = ref<any[]>([]), selectedUnitIds = ref<string[]>([]);
const caseForm = reactive({ dataset_name: '', kb_id: undefined as string | undefined, question: '', required: '', optional: '', forbidden: '', roles: '', reference_answer: '', answer_points: '', expected_kinds: [] as string[] });
const kindOptions = [{ label: '图', value: 'figure' }, { label: '公式', value: 'equation' }, { label: '说明', value: 'text' }, { label: '表格', value: 'table' }];
let disposed = false, refreshVersion = 0, pollTimer: ReturnType<typeof setTimeout> | undefined;
const active = computed(() => ['queued', 'running'].includes(selected.value?.status));
const canRetry = computed(() => ['cancelled', 'completed_with_errors'].includes(selected.value?.status) && selected.value?.details.some((d: any) => ['pending', 'error'].includes(d.status)) && !selected.value?.details.some((d: any) => d.status === 'running'));
const processed = computed(() => (selected.value?.details || []).filter((d: any) => ['completed', 'error'].includes(d.status)).length);
const progress = computed(() => selected.value?.details.length ? Math.round(processed.value * 100 / selected.value.details.length) : 0);
const currentQuestion = computed(() => selected.value?.details.find((d: any) => d.status === 'running')?.question);
const completedRuns = computed(() => (overview.value.runs || []).filter((r: any) => !r.legacy && r.status === 'completed'));
const retrievalMetrics = [{ key: 'recall', label: '召回率 Recall@10', help: '前 10 条命中的必需证据占比' }, { key: 'precision', label: '精确率 Precision@10', help: '前 10 条相关结果数 ÷ 10' }, { key: 'mrr', label: 'MRR@10', help: '前 10 条中首个相关结果排名的倒数' }, { key: 'coverage', label: '角色覆盖率', help: '检索结果覆盖的预期知识角色占比' }];
const answerMetrics = [{ key: 'correctness', label: '答案正确性', help: '与参考答案及评分要点的一致程度' }, { key: 'groundedness', label: '依据支持度', help: '回答论断被检索证据支持的程度' }, { key: 'completeness', label: '答案完整性', help: '回答对评分要点的覆盖程度' }, { key: 'pass_rate', label: '检索通过率', help: '召回率 ≥ 80% 且无禁止命中；不是答案通过率' }];
const trend = computed(() => overview.value.trend || []);
const trendLines = computed(() => [{ key: 'recall', color: '#7c3aed' }, { key: 'precision', color: '#2563eb' }, { key: 'coverage', color: '#22c55e' }].map(line => {
  const dots = trend.value.flatMap((r: any, i: number) => r[line.key] == null ? [] : [{ id: r.id, x: 35 + i * 500 / Math.max(trend.value.length - 1, 1), y: 160 - r[line.key] * 1.4, label: `${r.date} ${r[line.key]}%` }]);
  return { ...line, dots, points: dots.map((p: any) => `${p.x},${p.y}`).join(' ') };
}));
const scoreCol = (title: string, key: string) => ({ title, key, customRender: ({ record }: any) => key === 'mrr' ? number(record[key]) : pct(record[key]) });
const detailCols = [{ title: '问题', dataIndex: 'question' }, { title: '类型', dataIndex: 'question_type', width: 110 }, { title: '状态', key: 'status' }, scoreCol('Recall@10', 'recall'), scoreCol('Precision@10', 'precision'), scoreCol('MRR@10', 'mrr'), { title: '检索通过', key: 'pass' }, { title: '操作', key: 'action', width: 100 }];
const answerCols = [{ title: '问题', dataIndex: 'question' }, { title: '评审状态', key: 'judge' }, { title: '图片／公式', key: 'media' }, { title: '操作', key: 'action', width: 100 }];
const compareCols = [{ title: '策略', dataIndex: 'strategy_name' }, ...retrievalMetrics.map(m => ({ title: m.label, customRender: ({ record }: any) => m.key === 'mrr' ? number(record.metrics[m.key]) : pct(record.metrics[m.key]) })), { title: '时间', customRender: ({ record }: any) => time(record.created_at) }];
const goldenCols = [{ title: '问题', dataIndex: 'question' }, { title: '类型', dataIndex: 'question_type' }, { title: '必需证据数', customRender: ({ record }: any) => record.required_knowledge.length }, { title: '答案标注', customRender: ({ record }: any) => record.evaluation_config.reference_answer || record.evaluation_config.answer_points?.length ? '已配置' : '未配置' }, { title: '操作', key: 'action', width: 130 }];
const runCols = [{ title: '执行时间', customRender: ({ record }: any) => time(record.created_at) }, { title: '策略', dataIndex: 'strategy_name' }, { title: '状态', key: 'status' }, { title: '成功／总题数', customRender: ({ record }: any) => `${record.metrics.completed ?? '—'} / ${record.metrics.cases ?? '—'}` }, { title: '数据集版本', customRender: ({ record }: any) => record.config?.dataset_hash?.slice(0, 8) || '旧版' }, { title: '操作', key: 'action' }];
const regressionCols = [{ title: '问题', dataIndex: 'question' }, { title: '基准召回率', customRender: ({ record }: any) => pct(record.before) }, { title: '当前召回率', customRender: ({ record }: any) => pct(record.after) }];
function pct(v: any) { return v == null ? '—' : `${Math.round(v * 10000) / 100}%`; }
function number(v: any) { return v == null ? '—' : Number(v).toFixed(3); }
function time(v: string) { return v ? v.replace('T', ' ').slice(0, 19) : '—'; }
function metricValue(key: string) { const value = selected.value?.legacy ? null : selected.value?.metrics?.[key]; return key === 'mrr' ? number(value) : pct(value); }
function deltaText(v: any, mrr = false) { return v?.delta == null ? '无可比数据' : `${v.delta > 0 ? '+' : ''}${v.delta}${mrr ? '' : ' 个百分点'}`; }
function statusText(v: string) { return ({ pending: '待执行', queued: '待继续', running: '执行中', completed: '已完成', completed_with_errors: '部分执行失败', error: '执行失败', cancelled: '已停止' } as any)[v] || '尚未评估'; }
function judgeText(v: string) { return ({ scored: '模型已评审，待人工复核', disabled: '未启用', unconfigured: '缺少答案标注', unavailable: '评审不可用' } as any)[v] || '未评审'; }
function mediaText(row: any) { const p = row.presentation; if (!p) return '未检查'; const bad = p.missing.length + p.images.filter((i: any) => !i.resolved || i.available === false).length; const unknown = p.images.filter((i: any) => i.available == null).length; return `${bad ? `${bad} 项待处理` : unknown ? `${unknown} 张图片待验证` : '未发现缺项'} · ${p.images.length} 张图 · ${p.has_math ? '有公式标记' : '无公式标记'}`; }
const lines = (v: string) => [...new Set(v.split(/\r?\n/).map(s => s.trim()).filter(Boolean))];
function filterUnit(input: string, option: any) { return String(option.label).toLowerCase().includes(input.toLowerCase()); }
async function loadUnits() { selectedUnitIds.value = []; unitOptions.value = []; if (!caseForm.kb_id) return; const id = caseForm.kb_id; const { data } = await api.get('/units', { params: { kb_id: id } }); if (id === caseForm.kb_id) unitOptions.value = data.map((u: any) => ({ value: u.id, label: `${u.title} · ${u.document_title || u.source_chapter || ''} · ${u.id}` })); }
async function loadOverview(keepSelection = false) {
  const version = ++refreshVersion; loading.value = true; loadError.value = '';
  try { const { data } = await api.get('/evaluation/overview', { params: { dataset_name: dataset.value, run_id: keepSelection ? selected.value?.id : undefined } }); if (disposed || version !== refreshVersion) return;
    datasets.value = data.datasets; if (!dataset.value && datasets.value.length) { dataset.value = datasets.value[0]; await loadOverview(); return; }
    overview.value = data; if (!keepSelection) selected.value = data.latest;
    golden.value = dataset.value ? (await api.get('/evaluation/golden', { params: { dataset_name: dataset.value } })).data : [];
    if (selected.value?.details.some((d: any) => d.status === 'running') && !driving.value) schedulePoll();
  } catch { loadError.value = '评估数据加载失败，请刷新页面重试。'; } finally { if (version === refreshVersion) loading.value = false; }
}
async function changeDataset() { baselineId.value = undefined; selected.value = undefined; await loadOverview(); }
async function startRun() { if (!dataset.value || driving.value || active.value) return; driving.value = true;
  try { const { data } = await api.post('/evaluation/run', { dataset_name: dataset.value, strategy_id: strategyId.value, baseline_id: baselineId.value, judge_answers: judgeAnswers.value }); selected.value = data; await drive(data); }
  catch { loadError.value = '未能创建实验，请检查评估集、执行策略或基准是否满足条件。'; }
  finally { driving.value = false; }
}
async function drive(run: any) {
  driving.value = true; selected.value = run;
  try { while (!disposed && selected.value?.id === run.id && selected.value.status === 'queued') {
      const next = selected.value.details.find((d: any) => d.status === 'pending'); if (!next) break;
      selected.value = { ...selected.value, status: 'running', details: selected.value.details.map((d: any) => d.case_id === next.case_id ? { ...d, status: 'running' } : d) };
      selected.value = (await api.post(`/evaluation/runs/${run.id}/step`, { case_id: next.case_id })).data;
    }
    if (!disposed && selected.value?.status === 'completed') message.success('评估完成，可查看逐题结果');
  } catch { if (!disposed) { selected.value = (await api.get(`/evaluation/runs/${run.id}`)).data; message.warning('执行请求中断，已保存的结果仍可查看或继续'); } }
  finally { driving.value = false; if (!disposed) { await loadOverview(true); if (selected.value?.details.some((d: any) => d.status === 'running')) schedulePoll(); } }
}
function schedulePoll() { clearTimeout(pollTimer); pollTimer = setTimeout(async () => { if (disposed || driving.value || !selected.value) return; const id = selected.value.id; try { const { data } = await api.get(`/evaluation/runs/${id}`); if (selected.value?.id === id) selected.value = data; } catch { loadError.value = '进度刷新失败，稍后将自动重试'; } finally { if (!disposed && selected.value?.details.some((d: any) => d.status === 'running')) schedulePoll(); } }, 2500); }
async function cancelRun() { const { data } = await api.post(`/evaluation/runs/${selected.value.id}/cancel`); selected.value = data; if (!driving.value) schedulePoll(); message.info('已停止后续题目，当前题执行结束后会保存结果'); }
async function retryRun() { const { data } = await api.post(`/evaluation/runs/${selected.value.id}/retry`); await drive(data); }
async function selectRun(run: any) { selected.value = (await api.get(`/evaluation/runs/${run.id}`)).data; tab.value = 'retrieval'; await loadOverview(true); if (selected.value.details.some((d: any) => d.status === 'running')) schedulePoll(); }
async function editCase(row?: any) { editingId.value = row?.id; selectedUnitIds.value = [];
  Object.assign(caseForm, { dataset_name: row?.dataset_name || dataset.value || '', kb_id: row?.kb_id || kbs.value[0]?.id, question: row?.question || '', required: (row?.required_knowledge || []).join('\n'), optional: (row?.optional_knowledge || []).join('\n'), forbidden: (row?.forbidden_knowledge || []).join('\n'), roles: (row?.expected_roles || []).join('\n'), reference_answer: row?.evaluation_config?.reference_answer || '', answer_points: (row?.evaluation_config?.answer_points || []).join('\n'), expected_kinds: row?.evaluation_config?.expected_kinds || [] }); showCase.value = true; await loadUnits(); }
async function saveCase() { const required = [...new Set([...selectedUnitIds.value.map(id => `id:${id}`), ...lines(caseForm.required)])]; if (!caseForm.dataset_name.trim() || !caseForm.question.trim() || !caseForm.kb_id || !required.length) { message.warning('请填写评估集、问题、知识库和必需证据'); return; }
  saving.value = true; try { const payload = { dataset_name: caseForm.dataset_name.trim(), question: caseForm.question.trim(), kb_id: caseForm.kb_id, required_knowledge: required, optional_knowledge: lines(caseForm.optional), forbidden_knowledge: lines(caseForm.forbidden), expected_roles: lines(caseForm.roles), evaluation_config: { reference_answer: caseForm.reference_answer, answer_points: lines(caseForm.answer_points), expected_kinds: caseForm.expected_kinds } }; if (editingId.value) await api.put(`/evaluation/golden/${editingId.value}`, payload); else await api.post('/evaluation/golden', payload); showCase.value = false; dataset.value = payload.dataset_name; await loadOverview(); message.success('用例已保存，历史实验快照保持不变'); } finally { saving.value = false; } }
async function deleteCase(id: string) { await api.delete(`/evaluation/golden/${id}`); await loadOverview(); }
function csvCell(value: any) { let text = String(value ?? ''); if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; return `"${text.replace(/"/g, '""')}"`; }
function exportReport(format: string) { if (!selected.value) return; let content = JSON.stringify(selected.value, null, 2); if (format === 'csv') { const rows = [['问题', '类型', '状态', 'Recall@10', 'Precision@10', 'MRR@10', '角色覆盖率', '检索通过', '缺失证据', '禁止命中', '执行错误', '实际回答', '评审说明'], ...selected.value.details.map((d: any) => [d.question, d.question_type, d.status, d.recall, d.precision, d.mrr, d.coverage, d.pass, (d.missing || []).join('；'), (d.forbidden || []).join('；'), d.error, d.answer, d.judge?.reason])]; content = '\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\r\n'); }
  const url = URL.createObjectURL(new Blob([content], { type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = `evaluation-${selected.value.id}.${format}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
onMounted(async () => { try { const results = await Promise.all([api.get('/strategies'), api.get('/knowledge-bases')]); strategies.value = results[0].data; kbs.value = results[1].data; await loadOverview(); } catch { loadError.value = '初始化失败，请刷新后重试。'; } });
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer); });
</script>

<style scoped>
.eval-page{max-width:1440px;margin:auto;color:#263449}.hero,.run-heading,.card-head{display:flex;justify-content:space-between;align-items:center;gap:16px}.hero h2{margin:0;font-size:23px}.hero p,.hint{color:#7d899b;font-size:13px;line-height:1.7}.hero{margin-bottom:20px}.card{background:white;border:1px solid #e7edf5;border-radius:12px;padding:20px;margin-bottom:16px;min-width:0}.filters{display:flex;align-items:flex-end;gap:18px;flex-wrap:wrap}.filters > label:not(.ant-checkbox-wrapper){display:flex;flex-direction:column;gap:8px;font-size:13px}.filters .ant-select{width:230px}.filters .ant-checkbox-wrapper{padding-bottom:5px}.run-heading{flex-wrap:wrap;font-size:13px}.run-heading span{color:#8c97a7}.run-banner small{color:#718096}.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:16px 0}.kpi{margin:0;display:flex;flex-direction:column;gap:10px}.kpi span{color:#607188;font-size:13px}.kpi b{font-size:28px;color:#193b73}.kpi small{font-size:12px;color:#8c97a7}.chart-row{display:grid;grid-template-columns:minmax(0,2fr) minmax(240px,1fr);gap:16px}h3{font-size:15px;margin:0 0 14px}h4{margin-top:24px}.trend svg{width:100%;height:190px}.trend text{font-size:10px;fill:#8c97a7}.legend{display:flex;justify-content:center;gap:16px;font-size:12px}.type-row{margin:16px 0;font-size:13px}.form-grid,.review-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.prewrap{white-space:pre-wrap}.delta{display:block;margin-top:12px}.ant-alert{margin-bottom:16px}details{margin:20px 0;border-top:1px solid #e7edf5;padding-top:12px}summary{cursor:pointer;color:#3562ae}pre{white-space:pre-wrap;overflow-wrap:anywhere}li{overflow-wrap:anywhere}.review-grid ul{padding-left:18px}
@media(max-width:1000px){.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.chart-row{grid-template-columns:1fr}.hero{align-items:flex-start;flex-wrap:wrap}}
@media(max-width:600px){.filters label,.filters .ant-select{width:100%}.kpi-grid,.form-grid,.review-grid{grid-template-columns:1fr}.card{padding:14px}.hero h2{font-size:20px}.run-heading{flex-direction:column;align-items:flex-start}}
</style>
