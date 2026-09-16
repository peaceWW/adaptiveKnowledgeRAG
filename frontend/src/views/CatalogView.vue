<template>
  <div class="catalog-page">
    <div class="hero">
      <div>
        <h2>知识目录</h2>
        <p class="muted" style="margin: 0 0 8px">按上传文章的章节展开，叶子节点为该章抽取的知识点</p>
        <a-select v-model:value="kbId" class="kb-select" @change="load">
          <a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option>
        </a-select>
      </div>
      <div class="toolbar">
        <a-input v-model:value="keyword" allow-clear placeholder="搜索文章、章节或知识点" style="width: 240px" />
        <a-button @click="load">刷新目录</a-button>
        <a-button @click="resetView">Reset view</a-button>
        <a-button @click="direction = direction === 'horizontal' ? 'vertical' : 'horizontal'">
          {{ direction === "horizontal" ? "横向" : "纵向" }}
        </a-button>
      </div>
    </div>

    <div class="workspace">
      <section class="map-pane">
        <MindMap
          v-if="root"
          ref="mapRef"
          :root="root"
          :selected-id="selectedId"
          :collapsed="collapsed"
          :matches="matches"
          :direction="direction"
          @select="selectNode"
          @toggle="toggleNode"
        />
        <a-empty v-else description="请先选择知识库" />
      </section>

      <aside class="detail-pane">
        <template v-if="detail">
          <div class="detail-type">{{ nodeKindLabel }}</div>
          <h3>{{ detail.name }}</h3>
          <p class="detail-path">{{ (detail.breadcrumb || []).map((item: any) => item.name).join(" / ") || detail.path }}</p>
          <div class="detail-stats">
            <span>{{ detail.unit_count || evidenceItems.length }} 个知识点</span>
            <span>{{ (detail.documents || []).length }} 篇文档</span>
          </div>
          <div class="detail-actions">
            <a-button size="small" @click="clearSelection">清除选择</a-button>
            <a-popconfirm title="确定删除该节点？" :disabled="!detail.is_leaf" @confirm="removeNode">
              <a-button size="small" danger :disabled="!detail.is_leaf">删除</a-button>
            </a-popconfirm>
            <a-button size="small" type="primary" @click="showAdd = true">新增</a-button>
            <a-button size="small" @click="copyPath">复制路径</a-button>
          </div>

          <p v-if="detail.overview" class="section-hint">{{ detail.overview }}</p>

          <div v-if="!detail.is_leaf && (detail.children || []).length" class="child-section">
            <div class="section-title"><b>下级节点</b></div>
            <button v-for="child in detail.children" :key="child.id" type="button" @click="selectNode(child.id)">
              {{ child.name }}<small>{{ child.is_leaf ? "知识点" : "展开" }} →</small>
            </button>
          </div>

          <template v-if="evidenceItems.length">
            <div class="section-title evidence-title"><b>知识依据</b><small>{{ filteredEvidence.length }} 条</small></div>
            <a-segmented v-model:value="evidenceFilter" :options="evidenceFilters" block />
            <a-spin :spinning="loadingDetail">
              <div v-for="item in pagedEvidence" :key="item.id" class="evidence-card">
                <div>
                  <a-tag :color="item.lifecycle === 'AI_PROCESSED' ? 'orange' : 'blue'">{{ roleLabel(item.role) }}</a-tag>
                  <small v-if="item.lifecycle === 'AI_PROCESSED'">AI 抽取 · 待核对</small>
                </div>
                <button class="evidence-title-button" type="button" @click="openEvidence(item)">{{ item.title }}</button>
                <p>{{ (item.content || "").slice(0, 180) }}{{ (item.content || "").length > 180 ? "…" : "" }}</p>
                <div class="evidence-source">{{ item.document_title }}<span v-if="item.page"> · p.{{ item.page }}</span></div>
                <button class="source-link" type="button" @click="openEvidence(item)">查看依据{{ isPdf(item) ? "与原 PDF" : "" }} ↗</button>
              </div>
              <a-empty v-if="!loadingDetail && !filteredEvidence.length" description="暂无此类依据" />
              <a-pagination
                v-if="filteredEvidence.length > 6"
                v-model:current="evidencePage"
                simple
                :total="filteredEvidence.length"
                :page-size="6"
                class="evidence-pagination"
              />
            </a-spin>
          </template>
          <div v-else-if="!loadingDetail && !(detail.children || []).length" class="empty-coverage">
            <a-empty description="该分类尚无文档依据" />
          </div>
        </template>
        <a-empty v-else description="点击思维导图节点查看依据" />
      </aside>
    </div>

    <a-modal v-model:open="showAdd" title="新增子节点" @ok="addNode">
      <a-form layout="vertical">
        <a-form-item label="名称"><a-input v-model:value="newName" /></a-form-item>
        <a-form-item label="关联概念（逗号分隔）"><a-input v-model:value="newConcepts" /></a-form-item>
      </a-form>
    </a-modal>
    <a-modal v-model:open="showSource" :title="source?.title" :width="1200" :footer="null" destroy-on-close>
      <div v-if="source" class="source-modal">
        <div class="source-text">
          <div class="source-heading">
            <b>{{ source.document_title }}</b>
            <p>{{ source.chapter }} {{ source.section }} · 页码 {{ source.page || "未记录" }}</p>
            <a-tag>{{ source.lifecycle === "AI_PROCESSED" ? "AI 抽取内容，待核对" : source.lifecycle }}</a-tag>
          </div>
          <h4>{{ source.original ? "已保存的原文片段" : "知识点摘录" }}</h4>
          <div class="source-content" v-html="renderAnswer(source.original || source.content)"></div>
          <DocumentAsset
            v-if="source.image_key || source.image_url"
            :document-id="source.document_id || ''"
            :image-key="source.image_key"
            :image-url="source.image_key ? undefined : source.image_url"
            :alt="source.title"
          />
        </div>
        <PdfSourceViewer
          v-if="isPdf(source) && !textOnly"
          :document-id="source.document_id!"
          :filename="source.filename"
          :source-page="source.page"
          :source-key="source.id"
          @show-text="textOnly = true"
        />
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { message } from "ant-design-vue";
import { api } from "../api";
import MindMap from "../components/MindMap.vue";
import PdfSourceViewer from "../components/PdfSourceViewer.vue";
import DocumentAsset from "../components/DocumentAsset.vue";
import { renderAnswer } from "../answer";
import { roleLabels } from "../knowledge";

const PALETTE = ["blue", "green", "purple", "cyan"];
const ICONS: Record<string, string> = {
  document: "📄",
  section: "📑",
  unit: "📌",
};
const evidenceFilters = [
  { label: "全部", value: "all" },
  { label: "指标", value: "metrics" },
  { label: "约束", value: "constraints" },
  { label: "对比", value: "comparisons" },
];
const roleGroups: Record<string, string[]> = {
  metrics: ["metric", "parameter"],
  constraints: ["constraint", "rule", "limitation", "exception", "warning", "requirement", "assumption", "root_cause", "symptom"],
  comparisons: ["comparison"],
};

const kbs = ref<any[]>([]);
const kbId = ref<string>();
const nodes = ref<any[]>([]);
const selectedId = ref<string>("root");
const collapsed = reactive<Record<string, boolean>>({});
const keyword = ref("");
const direction = ref<"horizontal" | "vertical">("horizontal");
const detail = ref<any>(null);
const loadingDetail = ref(false);
const showAdd = ref(false);
const showSource = ref(false);
const newName = ref("");
const newConcepts = ref("");
const source = ref<any | null>(null);
const textOnly = ref(false);
const evidenceFilter = ref("all");
const evidencePage = ref(1);
const mapRef = ref<InstanceType<typeof MindMap> | null>(null);

const currentKb = computed(() => kbs.value.find((item) => item.id === kbId.value));
const matches = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  if (!q) return new Set<string>();
  return new Set(nodes.value.filter((item) => item.name.toLowerCase().includes(q)).map((item) => item.id));
});
const root = computed(() => {
  if (!currentKb.value) return null;
  const map = new Map(nodes.value.map((item) => [item.id, { ...item, children: [] as any[], isRoot: false, isLeaf: true, tone: "leaf", icon: ICONS[item.name] || "📘" }]));
  const roots: any[] = [];
  for (const node of map.values()) {
    if (node.parent_id && map.has(node.parent_id)) {
      map.get(node.parent_id).children.push(node);
      map.get(node.parent_id).isLeaf = false;
    } else {
      roots.push(node);
    }
  }
  const paint = (items: any[], inherited: string) => {
    items.forEach((item, index) => {
      const tone = item.level <= 1 ? PALETTE[index % PALETTE.length] : inherited;
      item.tone = item.children.length ? tone : "leaf";
      item.icon = item.unit_id || item.isLeaf ? ICONS.unit : item.level === 0 ? ICONS.document : ICONS.section;
      paint(item.children, tone);
    });
  };
  paint(roots, "blue");
  return {
    id: "root",
    name: currentKb.value.name,
    path: currentKb.value.name,
    isRoot: true,
    isLeaf: false,
    tone: "root",
    icon: "🔶",
    related_concepts: [],
    children: roots,
  };
});

const evidenceItems = computed(() => (detail.value?.quotes || []).map(toEvidence));
const filteredEvidence = computed(() =>
  evidenceItems.value.filter((item: any) => evidenceFilter.value === "all" || roleGroups[evidenceFilter.value]?.includes(item.role)),
);
const pagedEvidence = computed(() => filteredEvidence.value.slice((evidencePage.value - 1) * 6, evidencePage.value * 6));
const nodeKindLabel = computed(() => {
  const node = detail.value;
  if (!node) return "";
  if (node.id === "root") return "知识库总览";
  if (node.is_leaf) return "知识点";
  if (node.level === 0) return "文章";
  return "章节";
});

function roleLabel(role: string) {
  return roleLabels[role] || role || "知识点";
}

function isPdf(item: any) {
  return String(item?.filename || "").toLowerCase().endsWith(".pdf") && !!item?.document_id;
}

/** 目录引用对齐图谱证据字段，打开同一套原文 + PDF 弹窗。 */
function toEvidence(quote: any) {
  return {
    id: quote.id || quote.unit_id,
    title: quote.title,
    content: quote.content || quote.quote || "",
    original: quote.original || quote.quote || "",
    role: quote.role || quote.semantic_role,
    lifecycle: quote.lifecycle || "",
    document_id: quote.document_id,
    document_title: quote.document_title || quote.filename || "未关联文档",
    filename: quote.filename || "",
    page: quote.page || quote.source_page,
    chapter: quote.chapter || quote.source_chapter,
    section: quote.section || "",
    image_key: quote.image_key || "",
    image_url: quote.image_url || "",
  };
}

function openEvidence(item: any) {
  source.value = item;
  textOnly.value = false;
  showSource.value = true;
}

function ancestorsOf(id: string) {
  const byId = new Map(nodes.value.map((item) => [item.id, item]));
  const ids: string[] = [];
  let cursor = byId.get(id);
  while (cursor?.parent_id) {
    ids.push(cursor.parent_id);
    cursor = byId.get(cursor.parent_id);
  }
  return ids;
}

async function load() {
  if (!kbId.value) return;
  nodes.value = (await api.get(`/knowledge-bases/${kbId.value}/catalog`)).data;
  Object.keys(collapsed).forEach((key) => delete collapsed[key]);
  for (const node of nodes.value) {
    // 默认展开到章节层：先看文章章节结构，再点开章节看知识点叶子
    if (!node.is_leaf && node.level >= 1) collapsed[node.id] = true;
  }
  await selectNode("root");
}

async function selectNode(id: string) {
  selectedId.value = id;
  evidenceFilter.value = "all";
  evidencePage.value = 1;
  showSource.value = false;
  if (id === "root") {
    detail.value = {
      id: "root",
      name: currentKb.value?.name,
      path: currentKb.value?.name,
      is_leaf: false,
      breadcrumb: [{ name: currentKb.value?.name }],
      related_concepts: [currentKb.value?.domain].filter(Boolean),
      overview: currentKb.value?.description || "知识库根节点。展开文章可查看章节，章节下的叶子是抽取的知识点。",
      children: nodes.value.filter((item: any) => !item.parent_id),
      quotes: [],
    };
    return;
  }
  loadingDetail.value = true;
  try {
    detail.value = (await api.get(`/knowledge-bases/${kbId.value}/catalog/${id}`)).data;
  } finally {
    loadingDetail.value = false;
  }
}

function toggleNode(id: string) {
  collapsed[id] = !collapsed[id];
}

function resetView() {
  Object.keys(collapsed).forEach((key) => delete collapsed[key]);
  selectedId.value = "root";
  keyword.value = "";
  selectNode("root");
}

function clearSelection() {
  selectNode("root");
}

async function addNode() {
  if (!newName.value.trim() || !kbId.value) return;
  const parentId = selectedId.value === "root" ? null : selectedId.value;
  await api.post(`/knowledge-bases/${kbId.value}/catalog`, {
    name: newName.value.trim(),
    parent_id: parentId,
    related_concepts: newConcepts.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
  });
  showAdd.value = false;
  newName.value = "";
  newConcepts.value = "";
  message.success("已新增节点");
  const keep = selectedId.value;
  await load();
  if (keep && keep !== "root") await selectNode(keep);
}

async function removeNode() {
  if (!kbId.value || !detail.value?.id || detail.value.id === "root") return;
  await api.delete(`/knowledge-bases/${kbId.value}/catalog/${detail.value.id}`);
  message.success("已删除");
  await load();
}

function copyPath() {
  const text = detail.value?.path || "";
  navigator.clipboard.writeText(text);
  message.success("已复制路径");
}

watch(keyword, () => {
  for (const id of matches.value) {
    for (const ancestor of ancestorsOf(id)) collapsed[ancestor] = false;
  }
});
watch(evidenceFilter, () => {
  evidencePage.value = 1;
});

onMounted(async () => {
  kbs.value = (await api.get("/knowledge-bases")).data;
  kbId.value = kbs.value[0]?.id;
  await load();
});
</script>

<style scoped>
.catalog-page { max-width: 1440px; color: #26344c; }
.hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
.hero h2 { margin: 0 0 8px; }
.kb-select { width: 260px; }
.toolbar { display: flex; gap: 8px; align-items: center; }
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 355px;
  gap: 14px;
  min-height: calc(100vh - 180px);
}
.map-pane, .detail-pane {
  background: #fff;
  border: 1px solid #e4eaf3;
  border-radius: 12px;
  box-shadow: none;
  min-height: 0;
}
.detail-pane { padding: 20px; overflow: auto; }
.detail-type { font-size: 10px; letter-spacing: 1px; color: #6b8bd1; }
.detail-pane h3 { font-size: 20px; line-height: 1.5; margin: 8px 0; }
.detail-path { color: #95a0b2; font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.detail-stats { display: flex; gap: 16px; font-size: 12px; color: #6c7e97; border-bottom: 1px solid #eef2f7; padding-bottom: 16px; }
.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 4px; }
.section-title { display: flex; align-items: center; justify-content: space-between; margin: 20px 0 10px; font-size: 13px; }
.section-title small { color: #9aa6b8; }
.section-hint, .empty-coverage p { font-size: 11px; line-height: 1.7; color: #8997ab; }
.child-section > button {
  display: flex; justify-content: space-between; gap: 12px; width: 100%;
  border: 0; border-bottom: 1px solid #f0f3f8; background: white;
  padding: 12px 0; text-align: left; cursor: pointer; font-size: 12px;
}
.child-section small { white-space: nowrap; color: #8e9db3; }
.evidence-card { padding: 16px 0; border-bottom: 1px solid #edf1f7; }
.evidence-card small { font-size: 10px; color: #9aa4b4; }
.evidence-title-button {
  display: block; font-size: 13px; line-height: 1.7; font-weight: 600;
  text-align: left; border: 0; background: transparent; cursor: pointer; padding: 8px 0 0;
}
.evidence-card p { font-size: 12px; line-height: 1.8; color: #718098; margin: 8px 0; overflow-wrap: anywhere; }
.evidence-source { font-size: 10px; color: #96a1b2; overflow-wrap: anywhere; }
.source-link { border: 0; background: transparent; color: #4273c8; font-size: 11px; padding: 8px 0 0; cursor: pointer; }
.evidence-pagination { margin-top: 16px; }
.muted { color: #6b7280; font-size: 12px; }
.empty-coverage { margin-top: 30px; }
.source-modal { display: flex; gap: 20px; align-items: flex-start; }
.source-text { flex: 1; min-width: 0; max-height: 72vh; overflow: auto; }
.source-modal :deep(.pdf-viewer) { flex: 1; min-width: 0; }
.source-heading { padding-bottom: 12px; border-bottom: 1px solid #eef2f7; }
.source-heading p { font-size: 12px; color: #8b9cb1; }
.source-content { line-height: 1.9; font-size: 14px; overflow-wrap: anywhere; }
.source-content :deep(img) { max-width: 100%; }
.source-content :deep(pre) { overflow: auto; }
.source-content :deep(table) { display: block; overflow: auto; max-width: 100%; }
.source-content :deep(.katex-display) { overflow: auto; }
@media (max-width: 1100px) {
  .workspace { grid-template-columns: 1fr; }
  .source-modal { flex-direction: column; }
  .source-modal :deep(.pdf-viewer) { width: 100%; }
}
</style>
