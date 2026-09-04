<template>
  <div class="retrieval-page">
    <div class="hero">
      <div>
        <h2>检索中心</h2>
        <p>按文档管理关键字与元数据索引，控制写入、修改与删除</p>
      </div>
      <a-tabs v-model:activeKey="tab">
        <a-tab-pane key="index" tab="索引管理" />
        <a-tab-pane key="planner" tab="Retrieval Planner" />
      </a-tabs>
    </div>

    <div v-show="tab === 'index'" class="workspace">
      <aside class="doc-pane">
        <div class="pane-title">文档索引</div>
        <a-select v-model:value="kbId" allow-clear placeholder="全部知识库" class="full" @change="loadIndexes">
          <a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option>
        </a-select>
        <a-input-search
          v-model:value="keyword"
          allow-clear
          placeholder="搜索文件名或关键字"
          class="search"
          @search="loadIndexes"
        />
        <a-empty v-if="!docs.length" description="暂无文档索引" />
        <div
          v-for="doc in docs"
          :key="doc.id"
          class="doc-row"
          :class="{ selected: selectedId === doc.id }"
          @click="selectDoc(doc.id)"
        >
          <div class="doc-name">{{ doc.filename }}</div>
          <div class="doc-sub">
            <a-tag :color="doc.indexed ? 'blue' : 'default'">{{ doc.keyword_count }} 个关键字</a-tag>
            <span>{{ statusLabel(doc.status) }}</span>
          </div>
        </div>
      </aside>

      <section class="editor-pane" v-if="current">
        <div class="editor-head">
          <div>
            <h3>{{ current.filename }}</h3>
            <div class="muted">知识单元 {{ current.unit_count }} · {{ current.enabled ? "已启用" : "未启用" }}</div>
          </div>
          <a-space>
            <a-button :loading="saving" @click="saveIndex">保存修改</a-button>
            <a-button :loading="reindexing" @click="reindex">重建索引</a-button>
            <a-popconfirm title="清空该文档的关键字和元数据索引？文档本身不会删除。" @confirm="clearIndex">
              <a-button danger>清空索引</a-button>
            </a-popconfirm>
          </a-space>
        </div>

        <div class="card">
          <div class="card-head">
            <div class="card-title">关键字索引</div>
            <a-space>
              <a-input v-model:value="newKeyword" placeholder="新增关键字" style="width: 180px" @pressEnter="addKeyword" />
              <a-input-number v-model:value="newWeight" :min="0" :max="5" :step="0.1" style="width: 90px" />
              <a-button type="primary" @click="addKeyword">添加</a-button>
            </a-space>
          </div>
          <a-empty v-if="!draft.keywords.length" description="暂无关键字，可手动添加或点击重建索引" />
          <div v-for="(item, index) in draft.keywords" :key="item.keyword + index" class="kv-row">
            <a-input v-model:value="item.keyword" placeholder="关键字" />
            <a-input-number v-model:value="item.weight" :min="0" :max="5" :step="0.1" />
            <a-tag>{{ sourceLabel(item.source) }}</a-tag>
            <a-button type="text" danger @click="removeKeyword(index)">删除</a-button>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <div class="card-title">元数据索引</div>
            <a-space>
              <a-input v-model:value="newMetaKey" placeholder="字段名" style="width: 140px" @pressEnter="addMeta" />
              <a-input v-model:value="newMetaValue" placeholder="字段值" style="width: 180px" @pressEnter="addMeta" />
              <a-button type="primary" @click="addMeta">添加</a-button>
            </a-space>
          </div>
          <a-empty v-if="!draft.metadata.length" description="暂无元数据字段" />
          <div v-for="(item, index) in draft.metadata" :key="item.key + index" class="kv-row">
            <a-input v-model:value="item.key" placeholder="字段名" />
            <a-input v-model:value="item.value" placeholder="字段值" />
            <span class="muted">索引字段</span>
            <a-button type="text" danger @click="removeMeta(index)">删除</a-button>
          </div>
        </div>
      </section>

      <section v-else class="editor-pane empty">
        <a-empty description="选择左侧文档，管理其关键字与元数据索引" />
      </section>
    </div>

    <div v-show="tab === 'planner'">
      <a-card v-for="p in planners" :key="p.id" class="planner-card">
        <h3>{{ p.query_type }}</h3>
        <a-list :data-source="p.steps">
          <template #renderItem="{ item, index }">
            <a-list-item>{{ index + 1 }}. {{ item.type }}</a-list-item>
          </template>
        </a-list>
        <p class="muted">Completeness threshold：{{ p.completeness_threshold }} · Secondary：{{ p.secondary_retrieval }}</p>
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { message } from "ant-design-vue";
import { api } from "../api";

type KeywordItem = { keyword: string; weight: number; source: string };
type MetaItem = { key: string; value: string };

const tab = ref("index");
const kbs = ref<any[]>([]);
const docs = ref<any[]>([]);
const planners = ref<any[]>([]);
const kbId = ref<string | undefined>();
const keyword = ref("");
const selectedId = ref<string>();
const current = ref<any>();
const saving = ref(false);
const reindexing = ref(false);
const newKeyword = ref("");
const newWeight = ref(1);
const newMetaKey = ref("");
const newMetaValue = ref("");
const draft = reactive<{ keywords: KeywordItem[]; metadata: MetaItem[] }>({
  keywords: [],
  metadata: [],
});

function statusLabel(status: string) {
  const map: Record<string, string> = {
    uploaded: "已上传",
    parsing: "解析中",
    awaiting_strategy: "待确认策略",
    extracting: "抽取中",
    review: "待审核",
    indexed: "已索引",
  };
  return map[status] || status;
}

function sourceLabel(source: string) {
  if (source === "extracted") return "抽取";
  if (source === "manual") return "手工";
  return source || "手工";
}

function applyDraft(payload: any) {
  current.value = payload;
  draft.keywords = (payload.keywords || []).map((item: KeywordItem) => ({
    keyword: item.keyword,
    weight: Number(item.weight || 1),
    source: item.source || "manual",
  }));
  draft.metadata = Object.entries(payload.metadata || {}).map(([key, value]) => ({
    key,
    value: value == null ? "" : String(value),
  }));
}

function metadataPayload() {
  const result: Record<string, string> = {};
  for (const item of draft.metadata) {
    const key = item.key.trim();
    if (!key) continue;
    result[key] = item.value;
  }
  return result;
}

async function loadIndexes() {
  const params: Record<string, string> = {};
  if (kbId.value) params.kb_id = kbId.value;
  if (keyword.value.trim()) params.q = keyword.value.trim();
  docs.value = (await api.get("/retrieval/indexes", { params })).data;
  if (selectedId.value && !docs.value.some((item) => item.id === selectedId.value)) {
    selectedId.value = undefined;
    current.value = undefined;
  }
}

async function selectDoc(id: string) {
  selectedId.value = id;
  const payload = (await api.get(`/retrieval/indexes/${id}`)).data;
  applyDraft(payload);
}

function addKeyword() {
  const text = newKeyword.value.trim();
  if (!text) return;
  if (draft.keywords.some((item) => item.keyword.toLowerCase() === text.toLowerCase())) {
    message.warning("关键字已存在");
    return;
  }
  draft.keywords.push({ keyword: text, weight: Number(newWeight.value || 1), source: "manual" });
  newKeyword.value = "";
  newWeight.value = 1;
}

function removeKeyword(index: number) {
  draft.keywords.splice(index, 1);
}

function addMeta() {
  const key = newMetaKey.value.trim();
  if (!key) return;
  if (draft.metadata.some((item) => item.key === key)) {
    message.warning("字段已存在");
    return;
  }
  draft.metadata.push({ key, value: newMetaValue.value });
  newMetaKey.value = "";
  newMetaValue.value = "";
}

function removeMeta(index: number) {
  draft.metadata.splice(index, 1);
}

async function saveIndex() {
  if (!selectedId.value) return;
  saving.value = true;
  try {
    const payload = (
      await api.put(`/retrieval/indexes/${selectedId.value}`, {
        keywords: draft.keywords.filter((item) => item.keyword.trim()),
        metadata: metadataPayload(),
      })
    ).data;
    applyDraft(payload);
    await loadIndexes();
    message.success("索引已保存");
  } finally {
    saving.value = false;
  }
}

async function reindex() {
  if (!selectedId.value) return;
  reindexing.value = true;
  try {
    const payload = (await api.post(`/retrieval/indexes/${selectedId.value}/reindex`)).data;
    applyDraft(payload);
    await loadIndexes();
    message.success("已重建索引");
  } finally {
    reindexing.value = false;
  }
}

async function clearIndex() {
  if (!selectedId.value) return;
  await api.delete(`/retrieval/indexes/${selectedId.value}`);
  applyDraft({ ...current.value, keywords: [], metadata: {}, keyword_count: 0, indexed: false });
  await loadIndexes();
  message.success("已清空该文档索引");
}

onMounted(async () => {
  kbs.value = (await api.get("/knowledge-bases")).data;
  planners.value = (await api.get("/retrieval/planners")).data;
  await loadIndexes();
  if (docs.value.length) await selectDoc(docs.value[0].id);
});
</script>

<style scoped>
.retrieval-page { max-width: 1280px; }
.hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 8px; }
.hero h2 { margin: 0; font-size: 22px; }
.hero p { margin: 6px 0 0; color: #6b7280; }
.hero :deep(.ant-tabs) { min-width: 320px; }
.workspace { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 16px; align-items: start; }
.doc-pane, .editor-pane, .planner-card, .card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.doc-pane { padding: 16px; min-height: 560px; }
.pane-title { font-weight: 700; margin-bottom: 12px; }
.full, .search { width: 100%; margin-bottom: 10px; }
.doc-row { padding: 10px 8px; border-radius: 10px; cursor: pointer; }
.doc-row:hover, .doc-row.selected { background: #eff6ff; }
.doc-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-sub { display: flex; justify-content: space-between; gap: 8px; color: #6b7280; font-size: 12px; margin-top: 4px; }
.editor-pane { padding: 18px; min-height: 560px; }
.editor-pane.empty { display: grid; place-items: center; }
.editor-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 16px; }
.editor-head h3 { margin: 0 0 4px; }
.muted { color: #6b7280; font-size: 12px; }
.card { padding: 16px; margin-bottom: 14px; box-shadow: none; border: 1px solid #eef2f7; }
.card-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.card-title { font-weight: 700; }
.kv-row { display: grid; grid-template-columns: minmax(0, 1.4fr) 120px 80px 64px; gap: 8px; align-items: center; margin-bottom: 8px; }
.planner-card { margin-bottom: 12px; }
@media (max-width: 960px) {
  .hero { flex-direction: column; }
  .workspace { grid-template-columns: 1fr; }
}
</style>
