<template>
  <div class="catalog-page">
    <div class="hero">
      <div>
        <h2>知识目录 / Ontology</h2>
        <a-select v-model:value="kbId" class="kb-select" @change="load">
          <a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option>
        </a-select>
      </div>
      <div class="toolbar">
        <a-input v-model:value="keyword" allow-clear placeholder="Search nodes..." style="width: 220px" />
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
          <div class="detail-head">
            <div>
              <h3>Knowledge Entry Details: {{ detail.name }}</h3>
              <div class="path">Path: {{ (detail.breadcrumb || []).map((item: any) => item.name).join(" > ") || detail.path }}</div>
            </div>
            <a-space>
              <a-button size="small" @click="clearSelection">Clear</a-button>
              <a-popconfirm title="确定删除该节点？" :disabled="!detail.is_leaf" @confirm="removeNode">
                <a-button size="small" danger :disabled="!detail.is_leaf">Delete</a-button>
              </a-popconfirm>
              <a-button size="small" type="primary" @click="showAdd = true">+</a-button>
              <a-button size="small" @click="copyPath">Link</a-button>
              <a-button size="small" @click="exportNode">Export</a-button>
            </a-space>
          </div>

          <div class="card">
            <div class="card-title">Overview</div>
            <p>{{ detail.overview }}</p>
          </div>

          <div class="card">
            <div class="card-title">Knowledge Attributes</div>
            <div class="attr"><span>Owner</span><b>{{ session.username }}</b></div>
            <div class="attr"><span>Status</span><a-tag color="green">Active</a-tag></div>
            <div class="attr">
              <span>Labels</span>
              <div class="tags">
                <a-tag v-for="tag in detail.related_concepts || []" :key="tag">{{ tag }}</a-tag>
                <span v-if="!(detail.related_concepts || []).length" class="muted">无</span>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-title">{{ detail.is_leaf ? "原文引用" : "Related Resources" }}</div>
            <template v-if="detail.is_leaf">
              <a-spin :spinning="loadingDetail">
                <a-empty v-if="!detail.quotes?.length" description="该叶子节点暂无文章原文引用" />
                <div v-for="quote in detail.quotes || []" :key="quote.unit_id" class="quote">
                  <div class="quote-head">
                    <b>{{ quote.filename || "未关联文档" }}</b>
                    <a-tag>{{ quote.semantic_role }}</a-tag>
                  </div>
                  <div class="muted">{{ quote.title }} · {{ quote.source_chapter || "—" }} p.{{ quote.source_page || "—" }}</div>
                  <pre>{{ quote.original || quote.quote }}</pre>
                  <a-button type="link" size="small" @click="goReview(quote)">在审核中查看</a-button>
                </div>
              </a-spin>
            </template>
            <template v-else>
              <div class="muted">子节点</div>
              <div class="child-list">
                <a-tag v-for="child in detail.children || []" :key="child.id" @click="selectNode(child.id)">{{ child.name }}</a-tag>
              </div>
              <p class="hint">点击叶子节点可查看关联文章的原文引用。</p>
            </template>
          </div>
        </template>
        <a-empty v-else description="点击思维导图节点查看详情" />
      </aside>
    </div>

    <a-modal v-model:open="showAdd" title="新增子节点" @ok="addNode">
      <a-form layout="vertical">
        <a-form-item label="名称"><a-input v-model:value="newName" /></a-form-item>
        <a-form-item label="关联概念（逗号分隔）"><a-input v-model:value="newConcepts" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { api } from "../api";
import { useSession } from "../stores/session";
import MindMap from "../components/MindMap.vue";

const PALETTE = ["blue", "green", "purple", "cyan"];
const ICONS: Record<string, string> = {
  Semiconductor: "💾",
  DFT: "🔧",
  "Digital Design": "⚙️",
  "Physical Design": "📐",
  CDC: "🔁",
  "RTL Design": "📜",
  "Timing Analysis": "⏱️",
};

const router = useRouter();
const session = useSession();
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
const newName = ref("");
const newConcepts = ref("");
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
      item.icon = ICONS[item.name] || item.icon;
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
    if (!node.is_leaf && node.level >= 2) collapsed[node.id] = true;
  }
  await selectNode("root");
}

async function selectNode(id: string) {
  selectedId.value = id;
  if (id === "root") {
    detail.value = {
      id: "root",
      name: currentKb.value?.name,
      path: currentKb.value?.name,
      is_leaf: false,
      breadcrumb: [{ name: currentKb.value?.name }],
      related_concepts: [currentKb.value?.domain].filter(Boolean),
      overview: currentKb.value?.description || "知识库根节点，展开目录查看各领域主题。",
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

function exportNode() {
  const blob = new Blob([JSON.stringify(detail.value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${detail.value?.name || "catalog-node"}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function goReview(quote: any) {
  if (!quote.document_id) return;
  router.push({ name: "review", query: { documentId: quote.document_id } });
}

watch(keyword, () => {
  for (const id of matches.value) {
    for (const ancestor of ancestorsOf(id)) collapsed[ancestor] = false;
  }
});

onMounted(async () => {
  kbs.value = (await api.get("/knowledge-bases")).data;
  kbId.value = kbs.value[0]?.id;
  await load();
});
</script>

<style scoped>
.catalog-page { max-width: 1440px; }
.hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
.hero h2 { margin: 0 0 8px; }
.kb-select { width: 260px; }
.toolbar { display: flex; gap: 8px; align-items: center; }
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
  min-height: calc(100vh - 180px);
}
.map-pane, .detail-pane {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  min-height: 0;
}
.detail-pane { padding: 16px; overflow: auto; }
.detail-head { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
.detail-head h3 { margin: 0; font-size: 16px; }
.path, .muted, .hint { color: #6b7280; font-size: 12px; }
.card { background: #f8fafc; border-radius: 10px; padding: 12px; margin-bottom: 12px; }
.card-title { font-weight: 700; margin-bottom: 8px; }
.attr { display: flex; gap: 12px; margin: 6px 0; align-items: flex-start; }
.attr span { width: 72px; color: #6b7280; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; }
.quote { background: #fff; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
.quote-head { display: flex; justify-content: space-between; gap: 8px; }
.quote pre { white-space: pre-wrap; background: #fff1f2; padding: 8px; border-radius: 6px; margin: 8px 0 0; }
.child-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.child-list :deep(.ant-tag) { cursor: pointer; }
@media (max-width: 1100px) {
  .workspace { grid-template-columns: 1fr; }
}
</style>
