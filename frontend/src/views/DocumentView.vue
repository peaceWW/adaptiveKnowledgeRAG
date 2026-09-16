<template>
  <div class="doc-page">
    <div class="hero">
      <div>
        <h2>文档管理</h2>
        <p>上传、分析与抽取知识，跟进每份文档的处理状态</p>
        <a-select v-model:value="kbId" :disabled="uploading || extracting" placeholder="选择知识库" class="kb-select" @change="changeKb">
          <a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option>
        </a-select>
      </div>
      <a-button @click="loadDocs" :loading="loading">刷新文档</a-button>
    </div>
    <a-alert v-if="!loading && !kbs.length" type="info" show-icon message="请先创建知识库，再上传文档" style="margin-bottom: 16px">
      <template #action><a-button type="link" @click="router.push({ name: 'kb' })">创建知识库</a-button></template>
    </a-alert>
    <div class="summary-grid">
      <div v-for="item in summary" :key="item.label" class="summary-card"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
    </div>
    <div class="workflow-bar">
      <nav class="stepper" aria-label="文档处理流程">
        <button
          v-for="(item, index) in steps"
          :key="item"
          type="button"
          class="step"
          :class="{ active: currentStep === index, done: currentStep > index }"
          :disabled="extracting || uploading"
          :aria-current="currentStep === index ? 'step' : undefined"
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
          :disabled="uploading || !kbId"
          accept=".pdf,.md,.txt,.html"
          name="file"
          multiple
        >
          <cloud-upload-outlined class="cloud" />
          <p class="drop-title">{{ uploading ? `正在上传并分析 ${pendingUploads} 份文档…` : '拖拽文件到此处，或点击上传' }}</p>
          <p class="hint">支持 PDF、MD、TXT、HTML，单个文件最大 200MB · 支持多文件上传</p>
        </a-upload-dragger>

        <div class="file-list">
          <div class="list-head">文档列表 <span class="sub">{{ filteredDocs.length }} / {{ docs.length }} 份</span></div>
          <div class="list-tools">
            <a-input-search v-model:value="search" allow-clear placeholder="搜索文档名称" />
            <a-select v-model:value="statusFilter" :options="filterOptions" aria-label="按状态筛选" />
          </div>
          <a-empty v-if="!filteredDocs.length" :description="docs.length ? '没有符合条件的文档' : '尚未上传文档'" />
          <div
            v-for="doc in pagedDocs"
            :key="doc.id"
            class="file-row"
            :class="{ selected: focusId === doc.id }"
            tabindex="0"
            @keydown.enter.self="focusDoc(doc)"
            @click="focusDoc(doc)"
          >
            <span class="ext" :class="extClass(doc.filename)">{{ fileExt(doc.filename) }}</span>
            <div class="file-meta">
              <div class="name" :title="doc.filename">{{ doc.filename }}</div>
              <div class="sub">{{ fileExt(doc.filename) }}<template v-if="doc.size_bytes"> · {{ formatSize(doc.size_bytes) }}</template> · {{ doc.unit_count || 0 }} 个知识点 · {{ doc.enabled ? '已启用' : '未启用' }}</div>
            </div>
            <div class="file-status">
              <span :class="['status-text', statusTone(doc)]">{{ rowStatus(doc) }}</span>
              <a-progress v-if="isBusy(doc)" :percent="doc.parse_progress || 8" :show-info="false" size="small" />
            </div>
            <a-dropdown :trigger="['click']">
              <a-button type="text" size="small" aria-label="文档操作" @click.stop>⋯</a-button>
              <template #overlay>
                <a-menu>
                  <a-menu-item v-if="isPdf(doc)" @click="openPdf(doc)">查看原 PDF</a-menu-item>
                  <a-menu-item v-if="canEnable(doc)" @click="enableDoc(doc)">启用文档</a-menu-item>
                  <a-menu-item v-if="doc.enabled" @click="disableDoc(doc)">禁用文档</a-menu-item>
                  <a-menu-item v-if="doc.enabled" @click="goReview(doc)">进入知识审核</a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
            <a-popconfirm title="确定删除该文档及其知识点？" @confirm="removeDoc(doc)">
              <a-button type="text" class="trash" aria-label="删除文档" :disabled="isBusy(doc) || extracting" @click.stop>
                <delete-outlined />
              </a-button>
            </a-popconfirm>
          </div>
          <a-pagination v-if="filteredDocs.length > 10" v-model:current="page" :total="filteredDocs.length" :page-size="10" :show-size-changer="false" class="pagination" />
        </div>
      </div>

      <aside class="preview">
        <div class="preview-title">✦ AI 分析预览</div>
        <p v-if="preview" class="selected-name">{{ preview.filename }}</p>
        <a-alert v-if="preview?.status === 'failed'" type="error" show-icon message="处理失败" :description="preview.error_message || '请检查文件内容后重新上传。'" />
        <a-alert v-else-if="preview && isBusy(preview)" type="info" show-icon :message="rowStatus(preview)" description="处理状态将自动更新，请稍候。" />
        <div v-if="preview">
          <div class="block">
            <div class="muted">所属知识领域（来自知识库）</div>
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
          <a-button v-if="canProcess" type="primary" block size="large" :disabled="!preview.recommended_strategy" @click="useRecommended">
            使用推荐策略
          </a-button>
          <a-button v-if="canProcess" block class="secondary-action" @click="gotoStep(2)">手动选择策略</a-button>
          <a-button v-if="canEnable(preview)" type="primary" block @click="enableDoc(preview)">启用文档，进入审核流程</a-button>
          <a-button v-if="preview.enabled" type="primary" block @click="goReview(preview)">进入知识审核</a-button>
          <a-button type="link" block :disabled="!preview.classification" @click="gotoStep(1)">查看完整分析</a-button>
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
        <a-button type="primary" :disabled="!canProcess" @click="gotoStep(2)">下一步：选择策略</a-button>
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
          <div class="sub">{{ typeLabel(item.knowledge_type) }} · {{ chunkLabels[item.chunk_policy] || item.chunk_policy }}</div>
        </button>
      </div>
      <a-space class="actions">
        <a-button @click="currentStep = 1">上一步</a-button>
        <a-button type="primary" :disabled="!strategyId" @click="currentStep = 3">下一步：处理配置</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 3" class="card step-panel">
      <h3>处理配置</h3>
      <a-alert type="info" show-icon message="提取内容与文本拆分来自所选策略，确认抽取时会写入本篇文档的策略快照。" description="之后在策略中心改配置，不会改写已经抽过的文档；审核页按快照展示公式、图片、表格。" style="margin-bottom: 20px" />
      <template v-if="selectedStrategy">
        <h4>提取哪些内容</h4>
        <div class="result-rows">
          <div v-for="item in extractionCategories" :key="item.key" class="result-row">
            <span>{{ item.label }}</span>
            <a-tag :color="selectedPolicy[item.policy_key] ? 'blue' : 'default'">{{ selectedPolicy[item.policy_key] ? '已启用' : '已关闭' }}</a-tag>
          </div>
        </div>
        <p class="sub" v-if="selectedPolicy.images || selectedPolicy.tables || selectedPolicy.formulas">
          公式：{{ modeLabel(selectedPolicy.formula_mode) }} · 图片：{{ modeLabel(selectedPolicy.image_mode) }} · 表格：{{ modeLabel(selectedPolicy.table_mode) }}
        </p>
        <h4>文本如何拆分</h4>
        <a-form layout="vertical" class="config-form">
          <a-form-item label="拆分方式">
            <a-radio-group :value="selectedStrategy.chunk_policy || 'semantic_unit'" disabled>
              <a-radio-button v-for="(label, key) in chunkLabels" :key="key" :value="key">{{ label }}</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <p class="sub" v-if="selectedPolicy.text">单段最多 {{ selectedPolicy.chunk_size }} 字符<span v-if="selectedStrategy.chunk_policy === 'fixed_token'">，重叠 {{ selectedPolicy.chunk_overlap }} 字符</span>。公式、图片、表格不参与文本切分。</p>
          <p class="sub" v-else>本策略关闭了文本提取，不会生成文本知识单元。</p>
        </a-form>
      </template>
      <a-empty v-else description="请先选择策略" />
      <a-space class="actions">
        <a-button @click="currentStep = 2">上一步</a-button>
        <a-button type="primary" :disabled="!selectedStrategy" @click="currentStep = 4">下一步：审核设置</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 4" class="card step-panel">
      <h3>审核设置</h3>
      <a-form layout="vertical" class="config-form">
        <a-form-item>
          <div class="switch-row">
            <div>
              <div>知识质量审核</div>
              <div class="sub">由服务端质量校验规则生成审核任务，当前不支持自定义开关</div>
            </div>
            <a-switch v-model:checked="requireReview" disabled />
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
        <a-button type="primary" :loading="extracting" :disabled="!canProcess" @click="runExtract">开始抽取</a-button>
      </a-space>
    </div>

    <div v-show="currentStep === 5" class="card step-panel finish">
      <div class="done-mark">✓</div>
      <h3>完成</h3>
      <p>已抽取 {{ preview?.unit_count || 0 }} 个知识点。{{ preview?.enabled ? "文档已启用，可进入知识审核。" : "启用文档后，可进入知识审核。" }}</p>
      <a-space>
        <a-button @click="currentStep = 0">继续上传</a-button>
        <a-button v-if="canEnable(preview)" type="primary" @click="enableDoc(preview)">启用文档</a-button>
        <a-button type="primary" :disabled="!preview?.enabled" @click="goReview(preview)">进入知识审核</a-button>
      </a-space>
    </div>

    <a-modal v-model:open="showSource" :title="detailDoc?.filename" :width="1200" :footer="null" destroy-on-close @cancel="closePdf">
      <div v-if="detailDoc" class="pdf-modal">
        <PdfSourceViewer
          mode="document"
          :document-id="detailDoc.id"
          :filename="detailDoc.filename"
          :source-key="detailDoc.id"
        />
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { CloudUploadOutlined, DeleteOutlined } from "@ant-design/icons-vue";
import { api } from "../api";
import { chunkLabels, defaultExtractionPolicy, extractionCategories } from "../knowledge";
import PdfSourceViewer from "../components/PdfSourceViewer.vue";

const router = useRouter();
const route = useRoute();
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
const pendingUploads = ref(0);
const uploading = computed(() => pendingUploads.value > 0);
const loading = ref(true);
const search = ref('');
const statusFilter = ref('all');
const page = ref(1);
const filterOptions = [{ value: 'all', label: '全部状态' }, { value: 'busy', label: '处理中' }, { value: 'pending', label: '待选策略' }, { value: 'ready', label: '待启用' }, { value: 'enabled', label: '已启用' }, { value: 'failed', label: '处理失败' }];
function matchesStatus(doc: any, status: string) {
  if (status === 'busy') return isBusy(doc);
  if (status === 'pending') return ['analyzed', 'awaiting_strategy'].includes(doc.status);
  if (status === 'ready') return canEnable(doc);
  if (status === 'enabled') return doc.enabled;
  if (status === 'failed') return doc.status === 'failed';
  return true;
}
const filteredDocs = computed(() => docs.value.filter(doc => doc.filename.toLowerCase().includes(search.value.trim().toLowerCase()) && matchesStatus(doc, statusFilter.value)));
const pagedDocs = computed(() => filteredDocs.value.slice((page.value - 1) * 10, page.value * 10));
const summary = computed(() => [
  { label: '文档总数', value: docs.value.length },
  { label: '处理中', value: docs.value.filter(isBusy).length },
  { label: '待处理 / 待启用', value: docs.value.filter(doc => matchesStatus(doc, 'pending') || canEnable(doc)).length },
  { label: '处理失败', value: docs.value.filter(doc => doc.status === 'failed').length },
]);
watch([search, statusFilter], () => { page.value = 1; });
watch(() => filteredDocs.value.length, total => { page.value = Math.min(page.value, Math.max(1, Math.ceil(total / 10))); });
const detailDoc = ref<any>(null);
const showSource = ref(false);
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
const selectedStrategy = computed(() => strategies.value.find((item) => item.id === strategyId.value));
const selectedPolicy = computed(() => ({ ...defaultExtractionPolicy(), ...(selectedStrategy.value?.extraction_policy || {}) }));
const canProcess = computed(() => ['analyzed', 'awaiting_strategy'].includes(preview.value?.status) && !extracting.value);
watch(focusId, () => {
  currentStep.value = 0;
  strategyId.value = strategies.value.find(item => item.name === preview.value?.recommended_strategy)?.id;
  chunkPolicy.value = selectedStrategy.value?.chunk_policy || 'semantic_unit';
  maxTokens.value = selectedStrategy.value?.max_context_tokens || 2000;
  requireReview.value = true;
  autoEnable.value = false;
});
watch(selectedStrategy, (strategy) => {
  if (!strategy) return;
  chunkPolicy.value = strategy.chunk_policy || 'semantic_unit';
  maxTokens.value = strategy.max_context_tokens || 2000;
});
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
function modeLabel(value = "source") {
  return value === "vision" ? "截图 + 视觉识别" : "保留原稿";
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
  if (extracting.value) return;
  focusId.value = doc.id;
}
function gotoStep(index: number) {
  if (extracting.value || uploading.value) return;
  if (index > 0 && index < 5 && (!preview.value?.classification || isBusy(preview.value))) {
    message.warning('请等待文档分析完成');
    return;
  }
  if (index >= 2 && index <= 4 && !canProcess.value) {
    message.warning('只有分析完成、待选策略的文档可以开始抽取');
    return;
  }
  if (index >= 3 && index <= 4 && !strategyId.value) {
    message.warning('请先选择策略');
    return;
  }
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
  kbId.value = kbs.value.find(item => item.id === route.query.kb_id)?.id || kbs.value[0]?.id;
  strategies.value = (await api.get("/strategies")).data;
  await loadDocs();
}
async function changeKb() {
  docs.value = [];
  focusId.value = undefined;
  currentStep.value = 0;
  page.value = 1;
  search.value = '';
  statusFilter.value = 'all';
  await loadDocs();
}
let loadVersion = 0;
async function loadDocs() {
  if (!kbId.value) { loading.value = false; return; }
  const version = ++loadVersion;
  loading.value = true;
  try {
  const { data } = await api.get("/documents", { params: { kb_id: kbId.value } });
  if (version !== loadVersion) return;
  docs.value = data;
  if (!docs.value.find((item: any) => item.id === focusId.value)) {
    focusId.value = docs.value[0]?.id;
  }
  } finally { if (version === loadVersion) loading.value = false; }
}

async function upload(file: File) {
  if (!kbId.value) { message.warning('请先选择知识库'); return false; }
  if (!['PDF', 'MD', 'TXT', 'HTML'].includes(fileExt(file.name))) {
    message.error('当前解析器支持 PDF、MD、TXT、HTML，请转换格式后上传');
    return false;
  }
  if (!file.size) { message.error('不能上传空文件'); return false; }
  if (file.size > 200 * 1024 * 1024) {
    message.error("单文件不能超过 200MB");
    return false;
  }
  pendingUploads.value += 1;
  try {
    const form = new FormData();
    form.append("kb_id", kbId.value || "");
    form.append("file", file);
    const { data } = await api.post("/documents/upload", form);
    await loadDocs();
    focusId.value = data.id;
    if (data.status === 'failed') message.error(data.error_message || `${file.name} 分析失败`);
    else message.success(`${file.name} 已完成结构分析`);
  } catch {
    // 请求错误由统一反馈处理，阻止组件再次发起默认上传。
  } finally {
    pendingUploads.value -= 1;
  }
  return false;
}

function useRecommended() {
  if (!preview.value) return;
  const match = strategies.value.find((item) => item.name === preview.value?.recommended_strategy);
  if (!match) { message.warning('推荐策略不可用，请手动选择'); currentStep.value = 2; return; }
  strategyId.value = match.id;
  currentStep.value = 2;
}

async function runExtract() {
  if (!canProcess.value || !strategyId.value || !maxTokens.value) {
    message.warning("请先上传文档并选择策略");
    return;
  }
  extracting.value = true;
  try {
    const { data } = await api.post(`/documents/${preview.value.id}/confirm-strategy`, {
      strategy_id: strategyId.value,
      chunk_policy: chunkPolicy.value,
      max_context_tokens: maxTokens.value,
      require_human_review: requireReview.value,
      auto_enable: autoEnable.value,
    });
    await loadDocs();
    if (!['review', 'indexed'].includes(data.status)) {
      message.error(data.error_message || '抽取尚未完成，请在文档列表中查看状态');
      currentStep.value = 0;
      return;
    }
    currentStep.value = 5;
    message.success("知识抽取完成");
  } finally {
    extracting.value = false;
  }
}

function isPdf(doc: any) {
  return String(doc?.filename || "").toLowerCase().endsWith(".pdf") && !!doc?.id;
}

/** 文档操作只打开原 PDF 阅读器，不展示提取文本。 */
function openPdf(record: any) {
  if (!isPdf(record)) return;
  detailDoc.value = record;
  showSource.value = true;
}

function closePdf() {
  showSource.value = false;
  detailDoc.value = null;
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
  if (!record?.id || !record.enabled) return;
  router.push({ name: "review", query: { documentId: record.id } });
}

onMounted(() => {
  load().catch(() => { loading.value = false; });
  pollTimer = window.setInterval(() => {
    if (!loading.value && docs.value.some((item) => isBusy(item))) loadDocs().catch(() => {});
  }, 2500);
});
onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<style scoped>
.doc-page { width: 100%; min-width: 0; }
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
.stepper { display: flex; justify-content: space-between; gap: 12px; overflow-x: auto; padding: 4px; }
.workflow-bar { background: #fff; border: 1px solid #e6ebf2; padding: 18px 20px; border-radius: 12px; margin-bottom: 20px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 20px; }
.summary-card { display: flex; flex-direction: column; gap: 10px; background: #fff; border: 1px solid #e6ebf2; padding: 18px 22px; border-radius: 12px; color: #64748b; }
.summary-card strong { color: #172554; font-size: 28px; line-height: 1.2; }
.list-tools { display: grid; grid-template-columns: minmax(0, 1fr) 160px; gap: 12px; margin: 16px 0; }
.pagination { margin-top: 20px; text-align: right; }
.selected-name { overflow-wrap: anywhere; color: #475569; padding-bottom: 14px; border-bottom: 1px solid #e6ebf2; }
.secondary-action { margin-top: 10px; }
.step { white-space: nowrap; }
.step:disabled { cursor: wait; }
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
.upload-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 24%); gap: 24px; align-items: start; }
.left { min-width: 0; }
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
.file-list { margin-top: 20px; padding: 20px; background: #fff; border: 1px solid #e6ebf2; border-radius: 12px; min-height: 300px; }
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
  flex-shrink: 0;
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
.file-status { width: 110px; flex-shrink: 0; text-align: right; }
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
.result-rows { max-width: 560px; margin-bottom: 12px; }
.result-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f1f5f9; }
h4 { margin: 8px 0 12px; font-size: 15px; }
.switch-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.actions { margin-top: 16px; }
.finish { text-align: center; padding: 48px 24px; }
.done-mark {
  width: 56px; height: 56px; border-radius: 50%; margin: 0 auto 12px;
  background: #dbeafe; color: #2563eb; display: grid; place-items: center; font-size: 28px;
}
.pdf-modal :deep(.pdf-viewer) { min-height: 72vh; }
@media (max-width: 1100px) {
  .hero { flex-direction: column; }
  .stepper { justify-content: flex-start; }
  .upload-layout { grid-template-columns: 1fr; }
  .pdf-modal :deep(.pdf-viewer) { min-height: 60vh; }
}
@media (max-width: 600px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .summary-card { padding: 14px; }
  .list-tools { grid-template-columns: 1fr; }
  .file-list { padding: 12px; }
  .file-row { flex-wrap: wrap; gap: 8px; }
  .file-meta { flex-basis: calc(100% - 64px); }
  .file-status { margin-left: 50px; margin-right: auto; text-align: left; }
  .analysis-grid { grid-template-columns: 1fr; }
  .actions { display: flex; flex-wrap: wrap; }
}
</style>
