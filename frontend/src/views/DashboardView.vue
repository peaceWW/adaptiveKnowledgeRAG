<template>
  <div class="workbench">
    <div class="hero">
      <h2>工作台</h2>
      <p>欢迎使用 Adaptive Knowledge RAG 智能知识平台</p>
    </div>

    <div class="stat-grid">
      <button class="stat-card" type="button" @click="$router.push({ name: 'kb' })">
        <span class="stat-icon blue">📘</span>
        <div>
          <div class="stat-label">知识库</div>
          <div class="stat-value">{{ stats.knowledge_bases }}</div>
          <div class="stat-delta">+{{ deltas.knowledge_bases }} 本周</div>
        </div>
      </button>
      <button class="stat-card" type="button" @click="$router.push({ name: 'catalog' })">
        <span class="stat-icon purple">🧩</span>
        <div>
          <div class="stat-label">知识单元</div>
          <div class="stat-value">{{ formatNumber(stats.knowledge_units) }}</div>
          <div class="stat-delta">+{{ formatNumber(deltas.knowledge_units) }} 本周</div>
        </div>
      </button>
      <button class="stat-card alert" type="button" @click="$router.push({ name: 'review' })">
        <span class="stat-icon red">✅</span>
        <div>
          <div class="stat-label">待审核</div>
          <div class="stat-value">{{ stats.pending_reviews }}</div>
          <div class="stat-delta">+{{ deltas.pending_reviews }} 本周</div>
        </div>
      </button>
      <button class="stat-card" type="button" @click="$router.push({ name: 'chat' })">
        <span class="stat-icon teal">💬</span>
        <div>
          <div class="stat-label">今日问答</div>
          <div class="stat-value">{{ stats.chats_today }}</div>
          <div class="stat-delta">+{{ deltas.chats_today }} 今日</div>
        </div>
      </button>
    </div>

    <a-row :gutter="16">
      <a-col :span="12">
        <a-card class="panel" title="知识库健康度">
          <div class="health">
            <div class="gauge">
              <svg viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="50" class="gauge-track" />
                <circle
                  cx="60"
                  cy="60"
                  r="50"
                  class="gauge-value"
                  :stroke-dasharray="gaugeDash"
                  stroke-dashoffset="0"
                />
              </svg>
              <div class="gauge-label">
                <strong>{{ health.score }}</strong>
                <span>/ 100</span>
              </div>
            </div>
            <div class="health-metrics">
              <div v-for="item in healthItems" :key="item.label" class="health-row">
                <span>{{ item.label }}</span>
                <a-progress :percent="item.value" :show-info="true" size="small" />
              </div>
            </div>
          </div>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card class="panel" title="处理任务">
          <a-empty v-if="!tasks.length" description="暂无处理中的文档" />
          <div v-for="task in tasks" :key="task.id" class="task-row" @click="$router.push({ name: 'documents' })">
            <div>
              <div class="task-name">{{ task.filename }}</div>
              <a-tag :color="taskColor(task.status_label)">{{ task.status_label }}</a-tag>
            </div>
            <a-progress
              v-if="task.status_label === '处理中'"
              :percent="task.progress"
              style="width: 160px"
            />
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :span="12">
        <a-card class="panel" title="近期问答">
          <a-empty v-if="!queries.length" description="暂无问答记录" />
          <div v-for="item in queries" :key="item.id" class="query-row" @click="$router.push({ name: 'chat' })">
            <span class="query-text">{{ item.query }}</span>
            <span class="query-time">{{ item.time }}</span>
          </div>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card class="panel" title="检索效果趋势">
          <div class="legend">
            <span class="dot blue" />召回率
            <span class="dot orange" />准确率
          </div>
          <svg viewBox="0 0 420 180" class="chart">
            <line v-for="y in [30, 70, 110, 150]" :key="y" x1="36" :y1="y" x2="400" :y2="y" class="grid" />
            <polyline :points="recallPoints" class="line recall" />
            <polyline :points="precisionPoints" class="line precision" />
            <text
              v-for="(item, index) in trend"
              :key="item.date"
              :x="xAt(index)"
              y="172"
              class="axis"
            >{{ item.date }}</text>
          </svg>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../api";

const stats = ref({
  knowledge_bases: 0,
  knowledge_units: 0,
  pending_reviews: 0,
  chats_today: 0,
});
const deltas = ref({
  knowledge_bases: 0,
  knowledge_units: 0,
  pending_reviews: 0,
  chats_today: 0,
});
const health = ref({ score: 0, completeness: 0, accuracy: 0, recall: 0, consistency: 0 });
const tasks = ref<any[]>([]);
const queries = ref<any[]>([]);
const trend = ref<Array<{ date: string; recall: number; precision: number }>>([]);

const healthItems = computed(() => [
  { label: "完整度", value: health.value.completeness },
  { label: "准确率", value: health.value.accuracy },
  { label: "召回率", value: health.value.recall },
  { label: "一致性", value: health.value.consistency },
]);

const gaugeDash = computed(() => {
  const circ = 2 * Math.PI * 50;
  const value = Math.max(0, Math.min(health.value.score, 100)) / 100;
  return `${circ * value} ${circ}`;
});

function xAt(index: number) {
  const n = Math.max(trend.value.length - 1, 1);
  return 36 + (364 * index) / n;
}

function yAt(value: number) {
  const clamped = Math.max(70, Math.min(100, Number(value) || 70));
  return 150 - ((clamped - 70) / 30) * 120;
}

const recallPoints = computed(() =>
  trend.value.map((item, index) => `${xAt(index)},${yAt(item.recall)}`).join(" ")
);
const precisionPoints = computed(() =>
  trend.value.map((item, index) => `${xAt(index)},${yAt(item.precision)}`).join(" ")
);

function formatNumber(value: number) {
  return Number(value || 0).toLocaleString();
}

function taskColor(label: string) {
  if (label === "处理中") return "blue";
  if (label === "等待中") return "default";
  if (label === "失败") return "red";
  if (label === "已启用") return "green";
  return "success";
}

onMounted(async () => {
  const { data } = await api.get("/dashboard");
  stats.value = {
    knowledge_bases: data.knowledge_bases,
    knowledge_units: data.knowledge_units,
    pending_reviews: data.pending_reviews,
    chats_today: data.chats_today || 0,
  };
  deltas.value = data.deltas || deltas.value;
  health.value = data.health || health.value;
  tasks.value = data.recent_tasks || [];
  queries.value = data.recent_queries || [];
  trend.value = data.trend || [];
});
</script>

<style scoped>
.hero h2 {
  margin: 0;
  font-size: 22px;
}
.hero p {
  margin: 6px 0 18px;
  color: #6b7280;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.stat-card {
  display: flex;
  gap: 14px;
  align-items: center;
  text-align: left;
  background: #fff;
  border: 0;
  border-radius: 12px;
  padding: 18px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  cursor: pointer;
}
.stat-card.alert {
  background: #fff5f5;
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 22px;
}
.stat-icon.blue { background: #dbeafe; }
.stat-icon.purple { background: #ede9fe; }
.stat-icon.red { background: #fee2e2; }
.stat-icon.teal { background: #ccfbf1; }
.stat-label { color: #6b7280; font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 700; line-height: 1.2; }
.stat-delta { color: #10b981; font-size: 12px; margin-top: 2px; }
.panel { border-radius: 12px; }
.health { display: flex; gap: 24px; align-items: center; }
.gauge { position: relative; width: 140px; height: 140px; }
.gauge svg { width: 140px; height: 140px; transform: rotate(-90deg); }
.gauge-track { fill: none; stroke: #e5e7eb; stroke-width: 10; }
.gauge-value { fill: none; stroke: #2563eb; stroke-width: 10; stroke-linecap: round; }
.gauge-label {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  text-align: center;
}
.gauge-label strong { font-size: 28px; }
.gauge-label span { color: #6b7280; }
.health-metrics { flex: 1; }
.health-row { margin-bottom: 8px; }
.health-row span { color: #4b5563; font-size: 13px; }
.task-row, .query-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f3f4f6;
  cursor: pointer;
}
.task-name { font-weight: 600; margin-bottom: 4px; }
.query-text { color: #111827; }
.query-time { color: #9ca3af; font-size: 12px; }
.legend { display: flex; gap: 16px; color: #6b7280; font-size: 12px; margin-bottom: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.dot.blue { background: #3b82f6; }
.dot.orange { background: #f59e0b; }
.chart { width: 100%; height: 180px; }
.grid { stroke: #f3f4f6; }
.line { fill: none; stroke-width: 2.5; }
.line.recall { stroke: #3b82f6; }
.line.precision { stroke: #f59e0b; }
.axis { font-size: 10px; fill: #9ca3af; text-anchor: middle; }
@media (max-width: 1100px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
