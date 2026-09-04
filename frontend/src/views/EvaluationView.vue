<template>
  <div class="eval-page">
    <div class="hero">
      <a-tabs v-model:activeKey="tab">
        <a-tab-pane key="retrieval" tab="检索评估" />
        <a-tab-pane key="answer" tab="答案评估" />
        <a-tab-pane key="compare" tab="策略对比" />
        <a-tab-pane key="experiments" tab="实验管理" />
      </a-tabs>
      <a-space>
        <a-dropdown>
          <a-button>导出报告</a-button>
          <template #overlay>
            <a-menu @click="exportReport">
              <a-menu-item key="json">导出 JSON</a-menu-item>
              <a-menu-item key="csv">导出 CSV</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <a-button type="primary" :loading="running" @click="runEval">开始评估</a-button>
      </a-space>
    </div>

    <div class="filters">
      <div class="filter">
        <span>评估集</span>
        <a-select v-model:value="dataset" style="width: 220px" @change="loadOverview">
          <a-select-option v-for="item in datasets" :key="item" :value="item">{{ item }}</a-select-option>
        </a-select>
      </div>
      <div class="filter">
        <span>策略</span>
        <a-select v-model:value="strategyName" allow-clear placeholder="全部策略" style="width: 220px" @change="loadOverview">
          <a-select-option v-for="item in strategies" :key="item.id" :value="item.name">{{ item.name }}</a-select-option>
        </a-select>
      </div>
    </div>

    <div v-show="tab === 'retrieval'">
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">召回率 Recall@10</div>
          <div class="kpi-value">{{ kpis.recall.value }}%</div>
          <div class="kpi-delta" :class="{ up: kpis.recall.up }">{{ deltaText(kpis.recall) }} vs 上次</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">准确率 Precision@10</div>
          <div class="kpi-value">{{ kpis.precision.value }}%</div>
          <div class="kpi-delta" :class="{ up: kpis.precision.up }">{{ deltaText(kpis.precision) }} vs 上次</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">MRR</div>
          <div class="kpi-value">{{ kpis.mrr.value }}</div>
          <div class="kpi-delta" :class="{ up: kpis.mrr.up }">{{ deltaText(kpis.mrr, false) }} vs 上次</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">覆盖率 Coverage</div>
          <div class="kpi-value">{{ kpis.coverage.value }}%</div>
          <div class="kpi-delta" :class="{ up: kpis.coverage.up }">{{ deltaText(kpis.coverage) }} vs 上次</div>
        </div>
      </div>

      <div class="chart-row">
        <div class="card">
          <div class="card-title">指标趋势</div>
          <svg v-if="trend.length" viewBox="0 0 560 220" class="trend">
            <polyline v-for="line in trendLines" :key="line.key" fill="none" :stroke="line.color" stroke-width="2.5" :points="line.points" />
            <text v-for="(item, index) in trend" :key="item.date" :x="padX + index * stepX" y="210" text-anchor="middle" class="axis">{{ item.date }}</text>
          </svg>
          <div class="legend">
            <span><i style="background:#7c3aed" /> 召回率</span>
            <span><i style="background:#2563eb" /> 准确率</span>
            <span><i style="background:#22c55e" /> 覆盖率</span>
          </div>
          <a-empty v-if="!trend.length" description="运行评估后将显示趋势" />
        </div>
        <div class="card">
          <div class="card-title">问题类型分布</div>
          <div class="donut-wrap">
            <div class="donut" :style="{ background: donutGradient }">
              <div class="donut-hole">
                <b>{{ overview.total_questions || 0 }}</b>
                <span>总问题数</span>
              </div>
            </div>
            <div class="type-list">
              <div v-for="item in overview.question_types || []" :key="item.label" class="type-row">
                <i :style="{ background: item.color }" />
                <span>{{ item.label }}</span>
                <b>{{ item.percent }}%</b>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-show="tab === 'answer'">
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">Groundedness</div>
          <div class="kpi-value">{{ kpis.groundedness.value }}%</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">通过率</div>
          <div class="kpi-value">{{ kpis.pass_rate.value }}%</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Forbidden Hits</div>
          <div class="kpi-value">{{ overview.latest?.metrics?.forbidden_hits ?? 0 }}</div>
        </div>
      </div>
      <div class="card">
        <a-table :columns="detailCols" :data-source="overview.latest?.details || []" row-key="question" size="small" />
      </div>
    </div>

    <div v-show="tab === 'compare'">
      <div class="card">
        <a-table :columns="compareCols" :data-source="overview.strategy_compare || []" row-key="strategy_name" size="small" />
      </div>
    </div>

    <div v-show="tab === 'experiments'">
      <div class="card" style="margin-bottom: 12px">
        <div class="card-head">
          <div class="card-title">Golden Dataset</div>
          <a-button @click="showCase = true">新增用例</a-button>
        </div>
        <a-table :columns="goldenCols" :data-source="golden" row-key="id" size="small" />
      </div>
      <div class="card">
        <div class="card-title">实验记录</div>
        <a-table :columns="runCols" :data-source="overview.runs || []" row-key="id" size="small" />
      </div>
    </div>

    <a-modal v-model:open="showCase" title="新增评估用例" @ok="addCase">
      <a-form layout="vertical">
        <a-form-item label="评估集"><a-input v-model:value="caseForm.dataset_name" /></a-form-item>
        <a-form-item label="问题"><a-input v-model:value="caseForm.question" /></a-form-item>
        <a-form-item label="必中知识点（逗号分隔）"><a-input v-model:value="caseForm.required" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { message } from "ant-design-vue";
import { api } from "../api";

const tab = ref("retrieval");
const dataset = ref("cdc-v1");
const strategyName = ref<string>();
const datasets = ref<string[]>(["cdc-v1"]);
const strategies = ref<any[]>([]);
const golden = ref<any[]>([]);
const overview = ref<any>({ kpis: {}, trend: [], question_types: [], runs: [], strategy_compare: [] });
const running = ref(false);
const showCase = ref(false);
const caseForm = reactive({ dataset_name: "cdc-v1", question: "", required: "" });
const padX = 36;
const padY = 16;
const chartW = 500;
const chartH = 170;

const kpis = computed(() => ({
  recall: overview.value.kpis?.recall || { value: 0, delta: 0, up: true },
  precision: overview.value.kpis?.precision || { value: 0, delta: 0, up: true },
  mrr: overview.value.kpis?.mrr || { value: 0, delta: 0, up: true },
  coverage: overview.value.kpis?.coverage || { value: 0, delta: 0, up: true },
  groundedness: overview.value.kpis?.groundedness || { value: 0, delta: 0, up: true },
  pass_rate: overview.value.kpis?.pass_rate || { value: 0, delta: 0, up: true },
}));
const trend = computed(() => overview.value.trend || []);
const stepX = computed(() => (trend.value.length > 1 ? chartW / (trend.value.length - 1) : chartW));
const trendLines = computed(() => {
  const keys = [
    { key: "recall", color: "#7c3aed" },
    { key: "precision", color: "#2563eb" },
    { key: "coverage", color: "#22c55e" },
  ];
  return keys.map((line) => ({
    ...line,
    points: trend.value
      .map((item: any, index: number) => {
        const x = padX + index * stepX.value;
        const y = padY + chartH - (Number(item[line.key]) / 100) * chartH;
        return `${x},${y}`;
      })
      .join(" "),
  }));
});
const donutGradient = computed(() => {
  const items = overview.value.question_types || [];
  if (!items.length) return "#e5e7eb";
  let start = 0;
  const parts = items.map((item: any) => {
    const end = start + item.percent;
    const slice = `${item.color} ${start}% ${end}%`;
    start = end;
    return slice;
  });
  return `conic-gradient(${parts.join(",")})`;
});

const detailCols = [
  { title: "问题", dataIndex: "question" },
  { title: "类型", dataIndex: "question_type", width: 110 },
  { title: "Recall", dataIndex: "recall", width: 90 },
  { title: "Precision", dataIndex: "precision", width: 100 },
  { title: "Pass", dataIndex: "pass", width: 80 },
];
const compareCols = [
  { title: "策略", dataIndex: "strategy_name" },
  { title: "Recall", customRender: ({ record }: any) => pct(record.metrics?.recall) },
  { title: "Precision", customRender: ({ record }: any) => pct(record.metrics?.precision) },
  { title: "Coverage", customRender: ({ record }: any) => pct(record.metrics?.coverage) },
  { title: "时间", dataIndex: "created_at" },
];
const goldenCols = [
  { title: "评估集", dataIndex: "dataset_name", width: 120 },
  { title: "问题", dataIndex: "question" },
  { title: "类型", dataIndex: "question_type", width: 110 },
  { title: "Required", dataIndex: "required_knowledge" },
];
const runCols = [
  { title: "评估集", dataIndex: "dataset_name" },
  { title: "策略", dataIndex: "strategy_name" },
  { title: "Recall", customRender: ({ record }: any) => pct(record.metrics?.recall) },
  { title: "时间", dataIndex: "created_at" },
];

function pct(value?: number) {
  return `${Math.round(Number(value || 0) * 1000) / 10}%`;
}
function deltaText(item: { delta?: number; up?: boolean }, percent = true) {
  const value = Number(item?.delta || 0);
  const sign = value > 0 ? "↑" : value < 0 ? "↓" : "→";
  return percent ? `${sign} ${Math.abs(value)}%` : `${sign} ${Math.abs(value)}`;
}

async function loadOverview() {
  overview.value = (
    await api.get("/evaluation/overview", {
      params: { dataset_name: dataset.value, strategy_name: strategyName.value || undefined },
    })
  ).data;
  datasets.value = overview.value.datasets || datasets.value;
  golden.value = (await api.get("/evaluation/golden", { params: { dataset_name: dataset.value } })).data;
}

async function runEval() {
  running.value = true;
  try {
    await api.post("/evaluation/run", null, {
      params: { dataset_name: dataset.value, strategy_name: strategyName.value },
    });
    message.success("评估完成");
    await loadOverview();
  } finally {
    running.value = false;
  }
}

async function addCase() {
  if (!caseForm.question.trim()) {
    message.warning("请填写问题");
    return;
  }
  await api.post("/evaluation/golden", {
    dataset_name: caseForm.dataset_name,
    question: caseForm.question,
    required_knowledge: caseForm.required.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
  });
  showCase.value = false;
  caseForm.question = "";
  caseForm.required = "";
  message.success("已新增用例");
  await loadOverview();
}

function exportReport(info: { key: string }) {
  const payload = overview.value.latest || overview.value;
  if (info.key === "csv") {
    const rows = [["question", "type", "recall", "precision", "pass"]];
    for (const item of payload.details || []) {
      rows.push([item.question, item.question_type, item.recall, item.precision, item.pass]);
    }
    download("evaluation.csv", rows.map((row) => row.join(",")).join("\n"));
    return;
  }
  download("evaluation.json", JSON.stringify(payload, null, 2));
}

function download(name: string, content: string) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

onMounted(async () => {
  strategies.value = (await api.get("/strategies")).data;
  await loadOverview();
});
</script>

<style scoped>
.eval-page { max-width: 1280px; }
.hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.hero :deep(.ant-tabs) { flex: 1; }
.filters { display: flex; gap: 16px; margin: 4px 0 16px; flex-wrap: wrap; }
.filter { display: flex; align-items: center; gap: 8px; color: #6b7280; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.kpi, .card {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.kpi-label { color: #6b7280; font-size: 13px; }
.kpi-value { font-size: 28px; font-weight: 700; margin: 6px 0; }
.kpi-delta { color: #9ca3af; font-size: 12px; }
.kpi-delta.up { color: #16a34a; }
.chart-row { display: grid; grid-template-columns: minmax(0, 1.4fr) 360px; gap: 12px; }
.card-title { font-weight: 700; margin-bottom: 10px; }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.trend { width: 100%; height: 220px; }
.axis { font-size: 10px; fill: #9ca3af; }
.legend { display: flex; gap: 14px; color: #6b7280; font-size: 12px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
.donut-wrap { display: flex; gap: 16px; align-items: center; }
.donut {
  width: 150px;
  height: 150px;
  border-radius: 50%;
  display: grid;
  place-items: center;
}
.donut-hole {
  width: 92px;
  height: 92px;
  border-radius: 50%;
  background: #fff;
  display: grid;
  place-items: center;
  text-align: center;
}
.donut-hole b { font-size: 22px; }
.donut-hole span { font-size: 12px; color: #6b7280; }
.type-row { display: grid; grid-template-columns: 10px 1fr 40px; gap: 8px; align-items: center; margin: 8px 0; }
.type-row i { width: 10px; height: 10px; border-radius: 50%; }
@media (max-width: 1100px) {
  .kpi-grid, .chart-row { grid-template-columns: 1fr; }
}
</style>
