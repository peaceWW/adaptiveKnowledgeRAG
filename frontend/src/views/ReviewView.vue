<template>
  <div class="review-page">
    <div class="stats-bar">
      <div class="stats-left">
        <h2>知识单元</h2>
        <a-select
          v-model:value="documentId"
          class="doc-select"
          placeholder="请选择已启用的知识文档"
          @change="onDocumentChange"
        >
          <a-select-option v-for="doc in documents" :key="doc.id" :value="doc.id">
            {{ doc.filename }}
          </a-select-option>
        </a-select>
      </div>
      <div class="metrics">
        <div class="metric"><span>总量</span><b>{{ stats.total }}</b></div>
        <div class="metric"><span>已审核</span><b>{{ stats.reviewed }}</b></div>
        <div class="metric"><span>待审核</span><b class="pending">{{ stats.pending }}</b></div>
        <div class="metric"><span>通过率</span><b class="pass">{{ stats.passRate }}%</b></div>
      </div>
      <a-button
        type="primary"
        ghost
        :disabled="!pendingUnits.length"
        :loading="batching"
        @click="batchAcceptPending"
      >
        一键通过待审核
      </a-button>
    </div>

    <a-alert
      v-if="!documents.length"
      type="info"
      show-icon
      message="暂无已启用文档。请先到「文档管理」启用文档，才能拆分审核其中的知识点。"
      style="margin-bottom: 12px"
    />

    <div v-else class="workspace">
      <aside class="pane list-pane">
        <div class="pane-title">知识单元列表</div>
        <div class="list-tools">
          <a-input v-model:value="keyword" allow-clear placeholder="搜索知识单元..." />
          <a-select v-model:value="roleFilter" class="role-filter">
            <a-select-option value="">全部类型</a-select-option>
            <a-select-option v-for="role in roleOptions" :key="role" :value="role">
              {{ roleLabel(role) }}
            </a-select-option>
          </a-select>
        </div>
        <div class="unit-list">
          <button
            v-for="(item, index) in filteredUnits"
            :key="item.id"
            type="button"
            class="unit-item"
            :class="{ active: item.id === currentId, done: isReviewed(item) }"
            @click="select(item.id)"
          >
            <span class="idx">{{ index + 1 }}</span>
            <div class="unit-meta">
              <div class="unit-title" :title="item.title">{{ item.title }}</div>
              <div class="unit-tags">
                <a-tag :color="roleColor(item.semantic_role)">{{ roleLabel(item.semantic_role) }}</a-tag>
                <span class="conf">{{ percent(item.confidence) }}%</span>
              </div>
            </div>
          </button>
          <a-empty v-if="!filteredUnits.length" description="没有匹配的知识单元" />
        </div>
      </aside>

      <section class="pane source-pane">
        <div class="pane-head">
          <div class="pane-title">原文对照 <span v-if="selecting" class="muted">正在加载知识点…</span></div>
          <div class="pager">
            <a-button size="small" :disabled="!hasPrev" aria-label="上一条知识点" @click="goRelative(-1)">‹</a-button>
            <span>知识点 {{ currentIndex + 1 }} / {{ filteredUnits.length || 0 }}</span>
            <a-button size="small" :disabled="!hasNext" aria-label="下一条知识点" @click="goRelative(1)">›</a-button>
          </div>
        </div>
        <div v-if="documentId" class="source-tabs">
          <a-radio-group v-model:value="sourceMode" size="small" button-style="solid">
            <a-radio-button v-if="isPdf" value="pdf">PDF 原稿</a-radio-button>
            <a-radio-button v-for="item in extractionTabs" :key="item.key" :value="item.key">{{ item.label }} <span class="tab-count">{{ item.count }}</span></a-radio-button>
          </a-radio-group>
        </div>
        <div class="extraction-context">
          <template v-if="extractionInfo?.strategy_snapshot">
            抽取快照：{{ strategyLabel(extractionInfo.strategy_snapshot.name) }} · {{ chunkLabels[extractionInfo.strategy_snapshot.chunk_policy] }}
            <span>（以当时配置为准）</span>
            <div class="snapshot-flags">
              <a-tag v-for="item in extractionTabs" :key="item.key" :color="item.enabled ? 'blue' : 'default'">{{ item.label }} {{ item.enabled ? item.count : '关闭' }}</a-tag>
            </div>
          </template>
          <template v-else>历史提取结果 · 未记录策略快照，按现有知识单元分类展示</template>
        </div>
        <PdfSourceViewer v-if="documentId && isPdf" v-show="sourceMode === 'pdf'"
          :key="documentId" :document-id="documentId" :filename="sourceFilename"
          :source-page="detail?.source_page" :source-key="detail?.id || documentId" @show-text="sourceMode = 'text'" />
        <ExtractionResults v-if="documentId && sourceMode !== 'pdf'" :document-id="documentId" :units="units" :kind="sourceMode"
          :selected-id="currentId" :enabled="activeExtractionTab?.enabled" :custom-labels="customRoleLabels" @select="select" @locate="locateResult" />
      </section>

      <section class="pane form-pane">
        <template v-if="detail">
          <div class="pane-title form-title">知识单元 <span class="muted">抽取结果与审核</span></div>
          <a-form layout="vertical">
            <a-form-item label="类型">
              <a-select v-model:value="form.semantic_role" :disabled="!editing">
                <a-select-option v-for="role in roleOptions" :key="role" :value="role">
                  {{ roleLabel(role) }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="标题">
              <a-input v-model:value="form.title" :disabled="!editing" />
            </a-form-item>
            <a-form-item label="置信度">
              <div class="conf-row">
                <a-slider v-model:value="form.confidence" :min="0" :max="100" :disabled="!editing" />
                <b>{{ form.confidence }}%</b>
              </div>
            </a-form-item>
            <a-form-item label="重要性">
              <a-select v-model:value="form.importance" :disabled="!editing">
                <a-select-option value="high">高</a-select-option>
                <a-select-option value="medium">中</a-select-option>
                <a-select-option value="low">低</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="知识内容（抽取结果）">
              <a-textarea v-model:value="form.content" :rows="10" :disabled="!editing" />
            </a-form-item>
            <a-form-item v-if="assetUrl" label="图 / 公式截图">
              <img :src="assetUrl" class="asset-img" alt="unit asset" />
              <div v-if="detail?.unit_meta?.image_url" class="muted">图片地址 {{ detail.unit_meta.image_url }}</div>
              <div class="muted">{{ detail?.unit_meta?.caption || detail?.unit_meta?.latex || detail?.unit_meta?.anchor }}</div>
            </a-form-item>
          </a-form>
          <div class="actions">
            <a-button :disabled="selecting" :auto-insert-space="false" @click="review('reject', true)">拒绝</a-button>
            <a-button :disabled="selecting" :auto-insert-space="false" @click="toggleEdit">{{ editing ? "保存" : "编辑" }}</a-button>
            <a-button :disabled="selecting" type="primary" :auto-insert-space="false" @click="review('accept', true)">通过并下一个</a-button>
          </div>
        </template>
        <a-empty v-else description="选择左侧知识单元后开始审核" />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { message } from "ant-design-vue";
import { api } from "../api";
import PdfSourceViewer from '../components/PdfSourceViewer.vue';
import ExtractionResults from '../components/ExtractionResults.vue';
import { extractionCategories, extractionKind, roleLabels, chunkLabels, strategyLabel } from '../knowledge';

const PENDING = new Set(["DRAFT", "AI_PROCESSED", "PENDING_REVIEW", "APPROVED"]);
const REVIEWED = new Set(["PUBLISHED", "ARCHIVED", "DEPRECATED"]);
const roleOptions = Object.keys(roleLabels);
const roleColors: Record<string, string> = {
  definition: "green",
  principle: "blue",
  constraint: "cyan",
  example: "purple",
  rule: "orange",
  parameter: "geekblue",
  explanation: "default",
  formula: "gold",
  exception: "red",
  solution: "lime",
  classification: "magenta",
  reference: "default",
};

const route = useRoute();
const documents = ref<any[]>([]);
const units = ref<any[]>([]);
const detail = ref<any>(null);
const currentId = ref<string>();
const documentId = ref<string | undefined>();
const keyword = ref("");
const roleFilter = ref("");
const editing = ref(false);
const batching = ref(false);
const sourceBox = ref<HTMLElement | null>(null);
const assetUrl = ref("");
const sourceMode = ref('pdf');
const extractionInfo = ref<any>(null);
const sourceFilename = computed(() => detail.value?.filename || documents.value.find(doc => doc.id === documentId.value)?.filename || '');
const customRoleLabels = computed<Record<string, string>>(() => Object.fromEntries((extractionInfo.value?.strategy_snapshot?.role_rules || []).map((rule: any) => [rule.key, roleLabels[rule.key] || rule.label])));
const extractionTabs = computed(() => extractionInfo.value?.categories || extractionCategories.map(item => ({ ...item, count: units.value.filter(unit => extractionKind(unit) === item.key).length, enabled: null })));
const activeExtractionTab = computed(() => extractionTabs.value.find((item: any) => item.key === sourceMode.value));
const selecting = ref(false);
let selectionVersion = 0;
let unitLoadVersion = 0;
const isPdf = computed(() => sourceFilename.value.toLowerCase().endsWith('.pdf'));
watch(isPdf, value => { sourceMode.value = value ? 'pdf' : 'text'; });
const form = reactive({
  title: "",
  semantic_role: "definition",
  importance: "high",
  content: "",
  confidence: 80,
});

const filteredUnits = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  return units.value.filter((item) => {
    if (roleFilter.value && item.semantic_role !== roleFilter.value) return false;
    if (q && !`${item.title} ${item.content}`.toLowerCase().includes(q)) return false;
    return true;
  });
});
const pendingUnits = computed(() => units.value.filter((item) => PENDING.has(item.lifecycle)));
const stats = computed(() => {
  const total = units.value.length;
  const reviewed = units.value.filter((item) => REVIEWED.has(item.lifecycle)).length;
  const published = units.value.filter((item) => item.lifecycle === "PUBLISHED").length;
  return {
    total,
    reviewed,
    pending: total - reviewed,
    passRate: reviewed ? Math.round((published / reviewed) * 100) : 0,
  };
});
const currentIndex = computed(() => filteredUnits.value.findIndex((item) => item.id === currentId.value));
const hasPrev = computed(() => currentIndex.value > 0);
const hasNext = computed(() => currentIndex.value >= 0 && currentIndex.value < filteredUnits.value.length - 1);
const highlightParts = computed(() =>
  splitHighlight(
    detail.value?.source_text || detail.value?.source_span || detail.value?.original_text || detail.value?.content || "",
    detail.value,
  ),
);

function roleLabel(role = "") {
  return roleLabels[role] || customRoleLabels.value[role] || role;
}
function roleColor(role = "") {
  return roleColors[role] || "default";
}
function percent(value = 0) {
  return Math.round(Number(value) * 100);
}
function isReviewed(item: any) {
  return REVIEWED.has(item.lifecycle);
}
function toImportance(value = "core") {
  if (["high", "core"].includes(value)) return "high";
  if (["low", "optional"].includes(value)) return "low";
  return "medium";
}
function payload() {
  return {
    title: form.title,
    semantic_role: form.semantic_role,
    importance: form.importance,
    content: form.content,
    confidence: form.confidence / 100,
  };
}

function splitHighlight(text: string, unit: any) {
  if (!text) return [{ text: "暂无原文", hit: false }];
  const needles = [unit?.source_span, unit?.content].filter(Boolean).map((item: string) => item.trim());
  for (const needle of needles) {
    if (!needle) continue;
    const idx = text.indexOf(needle);
    if (idx >= 0) {
      return [
        { text: text.slice(0, idx), hit: false },
        { text: needle, hit: true },
        { text: text.slice(idx + needle.length), hit: false },
      ].filter((part) => part.text);
    }
    const short = needle.slice(0, 80);
    const fuzzy = text.indexOf(short);
    if (fuzzy >= 0) {
      const end = Math.min(text.length, fuzzy + Math.max(needle.length, 120));
      return [
        { text: text.slice(0, fuzzy), hit: false },
        { text: text.slice(fuzzy, end), hit: true },
        { text: text.slice(end), hit: false },
      ].filter((part) => part.text);
    }
  }
  return [{ text, hit: false }];
}

async function loadDocuments() {
  documents.value = (await api.get("/documents", { params: { enabled: true } })).data;
  const fromQuery = String(route.query.documentId || "");
  if (fromQuery && documents.value.some((doc) => doc.id === fromQuery)) {
    documentId.value = fromQuery;
  } else if (!documentId.value) {
    documentId.value = documents.value[0]?.id;
  }
}

async function loadUnits(keepId?: string, autoSelect = true) {
  const request = ++unitLoadVersion;
  if (!documentId.value) {
    units.value = [];
    detail.value = null;
    return;
  }
  const extraction = (await api.get(`/documents/${documentId.value}/extractions`)).data;
  if (request !== unitLoadVersion) return;
  extractionInfo.value = extraction;
  units.value = extraction.units;
  if (!autoSelect) return;
  const nextId =
    (keepId && units.value.some((item: any) => item.id === keepId) && keepId) ||
    pendingUnits.value[0]?.id ||
    units.value[0]?.id;
  if (nextId) await select(nextId);
  else detail.value = null;
}

async function onDocumentChange() {
  selectionVersion++;
  currentId.value = undefined;
  detail.value = null;
  extractionInfo.value = null;
  units.value = [];
  keyword.value = '';
  roleFilter.value = '';
  await loadUnits();
}

async function select(id: string) {
  const request = ++selectionVersion;
  currentId.value = id;
  editing.value = false;
  selecting.value = true;
  try {
  const { data } = await api.get(`/knowledge-units/${id}`);
  if (request !== selectionVersion) return;
  detail.value = data;
  form.title = detail.value.title;
  form.semantic_role = detail.value.semantic_role;
  form.importance = toImportance(detail.value.importance);
  form.content = detail.value.content;
  form.confidence = percent(detail.value.confidence);
  await loadAsset(detail.value);
  await nextTick();
  const hit = sourceBox.value?.querySelector(".hit");
  if (sourceMode.value === 'text') hit?.scrollIntoView({ block: "center" });
  } catch {
    if (request === selectionVersion) detail.value = null;
  } finally { if (request === selectionVersion) selecting.value = false; }
}

function revokeAsset() {
  if (assetUrl.value.startsWith("blob:")) URL.revokeObjectURL(assetUrl.value);
  assetUrl.value = "";
}

async function loadAsset(unit: any) {
  revokeAsset();
  const key = unit?.unit_meta?.image_key;
  const docId = unit?.document_id || documentId.value;
  if (unit?.unit_meta?.image_url) {
    assetUrl.value = unit.unit_meta.image_url;
    return;
  }
  if (!key || !docId) return;
  try {
    const res = await api.get(`/documents/${docId}/assets`, { params: { key }, responseType: "blob" });
    if (currentId.value !== unit.id) return;
    assetUrl.value = URL.createObjectURL(res.data);
  } catch {
    assetUrl.value = "";
  }
}

function goRelative(step: number) {
  const next = filteredUnits.value[currentIndex.value + step];
  if (next) select(next.id);
}
async function locateResult(id: string) {
  await select(id);
  if (detail.value?.id === id) sourceMode.value = isPdf.value ? 'pdf' : 'text';
}

async function toggleEdit() {
  if (!editing.value) {
    editing.value = true;
    return;
  }
  await review("save", false);
  message.success("已保存修改");
}

async function review(action: string, goNext: boolean) {
  if (!detail.value) return;
  const fromId = detail.value.id;
  const fromIndex = units.value.findIndex((item) => item.id === fromId);
  await api.post(`/knowledge-units/${fromId}/review`, { action, ...payload() });
  await loadUnits(fromId, false);
  if (goNext) {
    const next =
      units.value.slice(fromIndex + 1).find((item) => PENDING.has(item.lifecycle)) ||
      units.value.find((item) => PENDING.has(item.lifecycle)) ||
      units.value[fromIndex] ||
      units.value[0];
    if (next) await select(next.id);
    message.success(action === "reject" ? "已拒绝，已跳到下一条" : "已通过，已跳到下一条");
  } else if (units.value.some((item) => item.id === fromId)) {
    await select(fromId);
  }
}

async function batchAcceptPending() {
  const ids = pendingUnits.value.map((item) => item.id);
  if (!ids.length) return;
  batching.value = true;
  try {
    await api.post("/knowledge-units/batch-review", { unit_ids: ids, action: "accept", comment: "batch accept" });
    message.success(`已通过 ${ids.length} 条知识点`);
    await loadUnits();
  } finally {
    batching.value = false;
  }
}

watch(
  () => route.query.documentId,
  async (value) => {
    if (value && String(value) !== documentId.value) {
      await loadDocuments();
      await onDocumentChange();
    }
  },
);

onMounted(async () => {
  await loadDocuments();
  await loadUnits();
});
onBeforeUnmount(() => {
  selectionVersion++;
  unitLoadVersion++;
  revokeAsset();
});
</script>

<style scoped>
.review-page { width: 100%; min-width: 0; }
.stats-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.stats-left { display: flex; align-items: center; gap: 12px; min-width: 280px; }
.stats-left h2 { margin: 0; font-size: 20px; white-space: nowrap; }
.doc-select { width: 260px; }
.metrics { display: flex; gap: 18px; flex: 1; }
.metric { display: flex; flex-direction: column; min-width: 64px; }
.metric span { color: #6b7280; font-size: 12px; }
.metric b { font-size: 22px; line-height: 1.1; }
.metric .pending { color: #d97706; }
.metric .pass { color: #2563eb; }
.workspace {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr) 320px;
  gap: 12px;
  height: calc(100dvh - 168px);
  min-height: 620px;
}
.pane {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.pane-title { font-weight: 700; }
.pane-head, .list-pane { padding: 14px 14px 0; }
.list-pane { padding: 14px; }
.list-tools { display: grid; grid-template-columns: 1fr 110px; gap: 8px; margin: 12px 0; }
.role-filter { width: 100%; }
.unit-list { overflow: auto; flex: 1; }
.unit-meta { flex: 1; min-width: 0; }
.source-tabs { padding: 0 0 12px; }
.source-tabs :deep(.ant-radio-group) { display: flex; flex-wrap: wrap; gap: 6px; }
.tab-count { margin-left: 4px; font-size: 11px; }
.extraction-context { color: #64748b; font-size: 12px; padding-bottom: 12px; }
.snapshot-flags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.form-title { margin-bottom: 18px; }
.text-notice { color: #64748b; background: #f1f5f9; border-radius: 6px; padding: 12px; margin-bottom: 16px; font-size: 12px; white-space: normal; }
.unit-item {
  width: 100%;
  border: 0;
  background: transparent;
  display: flex;
  gap: 10px;
  text-align: left;
  padding: 10px 8px;
  border-radius: 10px;
  cursor: pointer;
}
.unit-item.active { background: #eff6ff; }
.unit-item.done { opacity: 0.7; }
.idx {
  width: 22px; color: #9ca3af; font-size: 12px; padding-top: 2px; flex: none;
}
.unit-title {
  font-weight: 600;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.unit-tags { display: flex; align-items: center; gap: 8px; }
.conf { color: #6b7280; font-size: 12px; }
.source-pane { padding: 14px; overflow: hidden; }
.pager { display: flex; align-items: center; gap: 8px; color: #6b7280; }
.pane-head { display: flex; justify-content: space-between; align-items: center; padding: 0 0 10px; }
.source-body {
  flex: 1;
  overflow: auto;
  white-space: pre-wrap;
  line-height: 1.7;
  color: #374151;
  padding-right: 4px;
  overflow-wrap: anywhere;
}
.hit {
  background: #fecaca;
  border-radius: 4px;
  box-shadow: 0 0 0 4px #fecaca;
}
.form-pane { padding: 14px 16px 16px; overflow: auto; }
.conf-row { display: grid; grid-template-columns: 1fr 48px; gap: 8px; align-items: center; }
.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.asset-img { max-width: 100%; max-height: 220px; object-fit: contain; border: 1px solid #e5e7eb; border-radius: 8px; }
.muted { color: #6b7280; font-size: 12px; margin-top: 6px; }
@media (max-width: 1400px) {
  .workspace { grid-template-columns: 220px minmax(0, 1fr) 280px; }
  .list-tools { grid-template-columns: 1fr; }
}
@media (max-width: 1200px) {
  .workspace { grid-template-columns: 220px minmax(0, 1fr); height: auto; }
  .source-pane, .list-pane { height: 780px; }
  .form-pane { grid-column: 1 / -1; }
}
@media (max-width: 700px) {
  .workspace { grid-template-columns: minmax(0, 1fr); }
  .list-pane { height: 260px; }
  .source-pane { height: 780px; padding: 10px; }
  .stats-left { min-width: 0; flex-wrap: wrap; }
  .doc-select { max-width: 100%; }
  .pane-head { flex-wrap: wrap; gap: 8px; }
}
</style>
