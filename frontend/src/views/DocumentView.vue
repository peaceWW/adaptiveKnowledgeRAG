<template>
  <div class="doc-page">
    <div class="hero">
      <div>
        <h2>文档上传</h2>
        <p>智能识别领域标签，匹配专家策略</p>
        <a-select v-model:value="kbId" size="small" class="kb-select" @change="loadDocs">
          <a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option>
        </a-select>
      </div>
      <nav class="stepper">
        <button
          v-for="(item, index) in steps"
          :key="item"
          type="button"
          class="step"
          :class="{ active: currentStep === index, done: currentStep > index }"
          @click="gotoStep(index)"
        >
          <span class="dot">{{ currentStep > index ? "✓" : index + 1 }}</span>
          {{ item }}
        </button>
      </nav>
    </div>

    <div v-show="currentStep === 0" class="upload-layout">
      <div class="left">
        <a-upload-dragger
          class="dropzone"
          :show-upload-list="false"
          :before-upload="upload"
          :disabled="uploading"
          accept=".pdf,.md,.txt,.html,.docx,.pptx,.ppt"
          name="file"
          multiple
        >
          <cloud-upload-outlined class="cloud" />
          <p class="drop-title">拖拽文件到此处，或 <span class="link">点击上传</span></p>
          <p class="hint">支持 PDF, DOCX, PPTX, MD, HTML 等格式，单个文件最大 200MB</p>
        </a-upload-dragger>

        <div class="file-list">
          <div class="list-head">已上传 ({{ docs.length }})</div>
          <a-empty v-if="!docs.length" description="尚未上传文档" />
          <div
            v-for="doc in docs"
            :key="doc.id"
            class="file-row"
            :class="{ selected: focusId === doc.id }"
            @click="focusDoc(doc)"
          >
            <span class="ext" :class="extClass(doc.filename)">{{ fileExt(doc.filename) }}</span>
            <div class="file-meta">
              <div class="name">{{ doc.filename }}</div>
              <div class="sub">{{ fileExt(doc.filename) }}<template v-if="doc.size_bytes"> · {{ formatSize(doc.size_bytes) }}</template></div>
            </div>
            <div class="file-status">
              <span :class="['status-text', statusTone(doc)]">{{ rowStatus(doc) }}</span>
              <a-progress v-if="isBusy(doc)" :percent="doc.parse_progress || 8" :show-info="false" size="small" />
            </div>
            <a-dropdown :trigger="['click']">
              <a-button type="text" size="small" @click.stop>⋯</a-button>
              <template #overlay>
                <a-menu>
                  <a-menu-item @click="openDetail(doc)">查看原文</a-menu-item>
                  <a-menu-item v-if="canEnable(doc)" @click="enableDoc(doc)">启用文档</a-menu-item>
                  <a-menu-item v-if="doc.enabled" @click="disableDoc(doc)">禁用文档</a-menu-item>
                  <a-menu-item v-if="doc.enabled || canEnable(doc)" @click="goReview(doc)">进入知识审核</a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
            <a-popconfirm title="确定删除该文档及其知识点？" @confirm="removeDoc(doc)">
              <a-button type="text" class="trash" @click.stop>
                <delete-outlined />
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>

      <aside class="preview">
        <div class="preview-title">✦ AI 分析预览</div>
        <div v-if="preview">
          <div class="block">
            <div class="muted">检测到的领域</div>
            <div class="domain-row">
              <strong>{{ previewDomain }}</strong>
              <span class="confidence">置信度 {{ previewConfidence }}%</span>
            </div>
          </div>
          <div class="block">
            <div class="muted">知识类型分布</div>
            <div v-for="item in previewScores" :key="item.label" class="score-row">
              <span>{{ item.label }}</span>
              <a-progress :percent="item.value" :show-info="false" size="small" />
              <em>{{ item.value }}%</em>
            </div>
          </div>
          <div class="block">
            <div class="muted">推荐策略</div>
            <div class="recommend">{{ strategyLabel(preview.recommended_strategy) }}</div>
          </div>
          <a-button type="primary" block size="large" :disabled="!preview" @click="useRecommended">
            使用推荐策略
          </a-button>
          <a-button type="link" block @click="currentStep = 1">查看完整分析</a-button>
        </div>
        <a-empty v-else description="上传文档后将显示分析结果" />
      </aside>
    </div>

    <div v-show="currentStep === 1" class="card step-panel">
      <h3>AI 分析</h3>
      <template v-if="preview">
        <p class="lead">{{ preview.filename }} · {{ statusLabel(preview.status) }}</p>
        <div class="analysis-grid">
          <div class="mini">
            <div class="muted">领域</div>
            <div>{{ previewDomain }}</div>
          </div>
          <div class="mini">
            <div class="muted">置信度</div>
            <div>{{ previewConfidence }}%</div>
          </div>
          <div class="mini">
            <div class="muted">知识类型</div>
            <div>{{ typeLabel(preview.classification?.knowledge_type) }}</div>
          </div>
          <div class="mini">
            <div class="muted">推荐策略</div>
            <div>{{ strategyLabel(preview.recommended_strategy) }}</div>
          </div>
        </div>
        <div class="muted">判定说明</div>
        <p>{{ preview.classification?.reason || "已完成启发式分类" }}</p>
        <div class="muted">知识类型分布</div>
        <div v-for="item in previewScores" :key="item.label" class="score-row wide">
          <span>{{ item.label }}</span>
          <a-progress :percent="item.value" size="small" />
        </div>
      </template>
      <a-empty v-else description="请先上传文档" />
      <a-space class="actions">
        <a-button @click="currentStep = 0">上一步</a-button>
        <a-button type="primary" :disabled="!preview" @click="currentStep = 2">下一步：选择策略</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 2" class="card step-panel">
      <h3>选择策略</h3>
      <p class="lead">根据文档领域与知识类型，选择最匹配的专家策略</p>
      <div class="strategy-grid">
        <button
          v-for="item in strategies"
          :key="item.id"
          type="button"
          class="strategy-card"
          :class="{ selected: strategyId === item.id }"
          @click="strategyId = item.id"
        >
          <div class="strategy-name">
            {{ strategyLabel(item.name) }}
            <a-tag v-if="item.name === preview?.recommended_strategy" color="blue">推荐</a-tag>
          </div>
          <div class="sub">{{ typeLabel(item.knowledge_type) }} · {{ item.chunk_policy || "semantic_unit" }}</div>
        </button>
      </div>
      <a-space class="actions">
        <a-button @click="currentStep = 1">上一步</a-button>
        <a-button type="primary" :disabled="!strategyId" @click="currentStep = 3">下一步：处理配置</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 3" class="card step-panel">
      <h3>处理配置</h3>
      <a-form layout="vertical" class="config-form">
        <a-form-item label="切分策略">
          <a-radio-group v-model:value="chunkPolicy">
            <a-radio-button value="semantic_unit">语义知识单元</a-radio-button>
            <a-radio-button value="section">按章节</a-radio-button>
            <a-radio-button value="fixed_token">固定 Token</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="最大上下文 Token">
          <a-input-number v-model:value="maxTokens" :min="256" :max="8000" :step="256" />
        </a-form-item>
      </a-form>
      <a-space class="actions">
        <a-button @click="currentStep = 2">上一步</a-button>
        <a-button type="primary" @click="currentStep = 4">下一步：审核设置</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 4" class="card step-panel">
      <h3>审核设置</h3>
      <a-form layout="vertical" class="config-form">
        <a-form-item>
          <div class="switch-row">
            <div>
              <div>高风险知识点必须人工审核</div>
              <div class="sub">抽取后进入待审核，不自动发布</div>
            </div>
            <a-switch v-model:checked="requireReview" />
          </div>
        </a-form-item>
        <a-form-item>
          <div class="switch-row">
            <div>
              <div>抽取完成后自动启用</div>
              <div class="sub">启用后该文档的知识点才会进入知识审核</div>
            </div>
            <a-switch v-model:checked="autoEnable" />
          </div>
        </a-form-item>
      </a-form>
      <a-space class="actions">
        <a-button @click="currentStep = 3">上一步</a-button>
        <a-button type="primary" :loading="extracting" @click="runExtract">开始抽取</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 5" class="card step-panel finish">
      <div class="done-mark">✓</div>
      <h3>完成</h3>
      <p>已完成知识抽取。{{ autoEnable ? "文档已自动启用，可进入知识审核。" : "请在列表中启用文档后，才能进入知识审核。" }}</p>
      <a-space>
        <a-button @click="currentStep = 0">继续上传</a-button>
        <a-button v-if="canEnable(preview) && !autoEnable" type="primary" @click="enableDoc(preview)">启用文档</a-button>
        <a-button type="primary" :disabled="!(preview?.enabled || autoEnable)" @click="goReview(preview)">进入知识审核</a-button>
      </a-space>
    </div>

    <a-drawer :open="Boolean(detailDoc)" width="720" title="文章原文" @close="detailDoc = null">
      <pre v-if="detailDoc" class="pane">{{ detailDoc.original_text || "暂无原文" }}</pre>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { CloudUploadOutlined, DeleteOutlined } from "@ant-design/icons-vue";
import { api } from "../api";

const router = useRouter();
const steps = ["上传文档", "AI分析", "选择策略", "处理配置", "审核设置", "完成"];
const currentStep = ref(0);
const kbs = ref<any[]>([]);
const docs = ref<any[]>([]);
const strategies = ref<any[]>([]);
const kbId = ref<string>();
const focusId = ref<string>();
const strategyId = ref<string>();
const chunkPolicy = ref("semantic_unit");
const maxTokens = ref(2000);
const requireReview = ref(true);
const autoEnable = ref(false);
const extracting = ref(false);
const uploading = ref(false);
const detailDoc = ref<any>(null);
let pollTimer: number | undefined;

const typeNames: Record<string, string> = {
  technical_concept: "技术规则",
  technical_specification: "设计规范",
  incident_case: "案例分析",
  api_document: "API 文档",
};
const strategyNames: Record<string, string> = {
  "Technical Knowledge V1": "技术知识库 V1",
  "Incident Case V1": "故障案例库 V1",
  "API Document V1": "API 知识库 V1",
};
const labels: Record<string, string> = {
  uploaded: "等待中",
  parsing: "分析中",
  analyzed: "已分析",
  awaiting_strategy: "待选策略",
  extracting: "抽取中",
  review: "待启用",
  indexed: "已抽取",
  failed: "失败",
};

const currentKb = computed(() => kbs.value.find((item) => item.id === kbId.value));
const preview = computed(() => docs.value.find((item) => item.id === focusId.value) || docs.value[0]);
const previewConfidence = computed(() => Math.round((preview.value?.classification?.confidence || 0) * 100) || 0);
const previewDomain = computed(() => {
  const domain = currentKb.value?.domain || "";
  if (domain === "semiconductor" || domain.includes("芯片") || domain.includes("半导体")) return "半导体设计";
  const type = preview.value?.classification?.knowledge_type || "";
  if (type.includes("incident")) return "故障案例";
  if (type.includes("api")) return "API 文档";
  return currentKb.value?.name || "通用知识";
});
const previewScores = computed(() => {
  const scores = preview.value?.classification?.scores || {};
  const rows = Object.entries(scores).map(([key, value]) => ({
    label: typeNames[key] || key,
    value: Math.round(Number(value) * 100),
  }));
  return rows.sort((a, b) => b.value - a.value).slice(0, 3);
});

function typeLabel(value = "") {
  return typeNames[value] || value || "--";
}
function strategyLabel(name = "") {
  return strategyNames[name] || name || "--";
}
function statusLabel(status: string) {
  return labels[status] || status;
}
function canEnable(record: any) {
  return record && !record.enabled && ["review", "indexed"].includes(record.status);
}
function isBusy(doc: any) {
  return ["uploaded", "parsing", "extracting"].includes(doc.status);
}
function rowStatus(doc: any) {
  if (doc.status === "parsing" || (doc.status === "uploaded" && (doc.parse_progress || 0) > 0)) {
    return `分析中 ${doc.parse_progress || 8}%`;
  }
  if (doc.status === "extracting") return `抽取中 ${doc.parse_progress || 0}%`;
  return statusLabel(doc.status);
}
function statusTone(doc: any) {
  if (["failed"].includes(doc.status)) return "bad";
  if (["uploaded", "parsing", "extracting", "awaiting_strategy"].includes(doc.status)) return "busy";
  return "ok";
}
function fileExt(name = "") {
  return (name.split(".").pop() || "FILE").toUpperCase();
}
function extClass(name = "") {
  const ext = fileExt(name).toLowerCase();
  if (ext === "pdf") return "pdf";
  if (["doc", "docx"].includes(ext)) return "doc";
  if (["ppt", "pptx"].includes(ext)) return "ppt";
  return "md";
}
function formatSize(bytes = 0) {
  if (!bytes) return "--";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function focusDoc(doc: any) {
  focusId.value = doc.id;
}
function gotoStep(index: number) {
  if (index > 0 && !preview.value) {
    message.warning("请先上传文档");
    return;
  }
  if (index === 5 && !["review", "indexed"].includes(preview.value?.status)) {
    message.warning("请先完成知识抽取");
    return;
  }
  currentStep.value = index;
}

async function load() {
  kbs.value = (await api.get("/knowledge-bases")).data;
  kbId.value = kbId.value || kbs.value[0]?.id;
  strategies.value = (await api.get("/strategies")).data;
  strategyId.value = strategies.value[0]?.id;
  await loadDocs();
}
async function loadDocs() {
  docs.value = (await api.get("/documents", { params: { kb_id: kbId.value } })).data;
  if (!docs.value.find((item: any) => item.id === focusId.value)) {
    focusId.value = docs.value[0]?.id;
  }
}

async function upload(file: File) {
  if (file.size > 200 * 1024 * 1024) {
    message.error("单文件不能超过 200MB");
    return false;
  }
  uploading.value = true;
  try {
    const form = new FormData();
    form.append("kb_id", kbId.value || "");
    form.append("file", file);
    const { data } = await api.post("/documents/upload", form);
    await loadDocs();
    focusId.value = data.id;
    message.success(`${file.name} 已完成结构分析`);
  } finally {
    uploading.value = false;
  }
  return false;
}

function useRecommended() {
  if (!preview.value) return;
  const match = strategies.value.find((item) => item.name === preview.value?.recommended_strategy);
  strategyId.value = match?.id || strategyId.value;
  currentStep.value = 2;
}

async function runExtract() {
  if (!preview.value || !strategyId.value) {
    message.warning("请先上传文档并选择策略");
    return;
  }
  extracting.value = true;
  try {
    await api.post(`/documents/${preview.value.id}/confirm-strategy`, {
      strategy_id: strategyId.value,
      chunk_policy: chunkPolicy.value,
      max_context_tokens: maxTokens.value,
      require_human_review: requireReview.value,
      auto_enable: autoEnable.value,
    });
    await loadDocs();
    currentStep.value = 5;
    message.success("知识抽取完成");
  } finally {
    extracting.value = false;
  }
}

async function openDetail(record: any) {
  detailDoc.value = (await api.get(`/documents/${record.id}`)).data;
}
async function enableDoc(record: any) {
  await api.post(`/documents/${record.id}/enable`);
  message.success("已启用");
  await loadDocs();
}
async function disableDoc(record: any) {
  await api.post(`/documents/${record.id}/disable`);
  message.success("已禁用");
  await loadDocs();
}
async function removeDoc(record: any) {
  await api.delete(`/documents/${record.id}`);
  if (focusId.value === record.id) focusId.value = undefined;
  await loadDocs();
}
function goReview(record: any) {
  if (!record?.id) return;
  router.push({ name: "review", query: { documentId: record.id } });
}

onMounted(() => {
  load();
  pollTimer = window.setInterval(() => {
    if (docs.value.some((item) => isBusy(item))) loadDocs();
  }, 2500);
});
onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<style scoped>
.doc-page { max-width: 1280px; }
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 18px;
}
.hero h2 { margin: 0; font-size: 22px; }
.hero p { margin: 6px 0 10px; color: #6b7280; }
.kb-select { width: 220px; }
.stepper { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0; padding-top: 6px; }
.step {
  border: 0;
  background: transparent;
  color: #9ca3af;
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  padding: 0;
}
.step .dot {
  width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; background: #e5e7eb; font-size: 11px;
}
.step:not(:last-child)::after {
  content: "";
  width: 28px;
  height: 1px;
  background: #e5e7eb;
  margin: 0 8px;
}
.step.active, .step.done { color: #2563eb; }
.step.active .dot, .step.done .dot { background: #2563eb; color: #fff; }
.step.done:not(:last-child)::after, .step.active:not(:last-child)::after { background: #93c5fd; }
.upload-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 18px; align-items: start; }
.dropzone :deep(.ant-upload-drag) {
  border: 1.5px dashed #93c5fd;
  background: #f8fbff;
  border-radius: 12px;
  padding: 28px 16px;
}
.cloud { font-size: 42px; color: #2563eb; }
.drop-title { margin: 8px 0 4px; font-size: 15px; }
.link { color: #2563eb; }
.hint { color: #9ca3af; font-size: 12px; margin: 0; }
.file-list { margin-top: 18px; }
.list-head { font-weight: 600; margin-bottom: 8px; }
.file-row {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 8px;
  border-radius: 10px;
  cursor: pointer;
}
.file-row.selected, .file-row:hover { background: #eff6ff; }
.ext {
  width: 42px; height: 42px; border-radius: 8px;
  display: grid; place-items: center; color: #fff; font-size: 11px; font-weight: 700;
}
.ext.pdf { background: #ef4444; }
.ext.doc { background: #2563eb; }
.ext.ppt { background: #ea580c; }
.ext.md { background: #0f766e; }
.file-meta { flex: 1; min-width: 0; }
.name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { color: #6b7280; font-size: 12px; }
.file-status { width: 110px; text-align: right; }
.status-text { font-size: 12px; }
.status-text.busy { color: #2563eb; }
.status-text.ok { color: #6b7280; }
.status-text.bad { color: #dc2626; }
.trash { color: #9ca3af; }
.preview, .card, .step-panel {
  background: #fff;
  border-radius: 12px;
  padding: 18px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.preview-title { font-weight: 700; margin-bottom: 16px; }
.block { margin-bottom: 18px; }
.muted { color: #6b7280; font-size: 12px; margin-bottom: 6px; }
.domain-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 18px; }
.confidence { color: #2563eb; font-size: 13px; font-weight: 600; }
.score-row { display: grid; grid-template-columns: 72px 1fr 40px; gap: 8px; align-items: center; margin: 8px 0; font-size: 13px; }
.score-row em { font-style: normal; color: #6b7280; text-align: right; }
.score-row.wide { grid-template-columns: 88px 1fr; }
.recommend { padding: 10px 12px; background: #eff6ff; border-radius: 8px; color: #1d4ed8; font-weight: 600; }
.lead { color: #6b7280; }
.analysis-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 12px 0 20px; }
.mini { background: #f8fafc; border-radius: 10px; padding: 12px; }
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 8px 0 20px; }
.strategy-card {
  text-align: left;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 12px;
  padding: 14px;
  cursor: pointer;
}
.strategy-card.selected { border-color: #2563eb; background: #eff6ff; }
.strategy-name { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 6px; }
.config-form { max-width: 560px; }
.switch-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.actions { margin-top: 16px; }
.finish { text-align: center; padding: 48px 24px; }
.done-mark {
  width: 56px; height: 56px; border-radius: 50%; margin: 0 auto 12px;
  background: #dbeafe; color: #2563eb; display: grid; place-items: center; font-size: 28px;
}
.pane { white-space: pre-wrap; background: #f8fafc; padding: 12px; max-height: 70vh; overflow: auto; }
@media (max-width: 1100px) {
  .hero { flex-direction: column; }
  .stepper { justify-content: flex-start; }
  .upload-layout { grid-template-columns: 1fr; }
}
</style>
