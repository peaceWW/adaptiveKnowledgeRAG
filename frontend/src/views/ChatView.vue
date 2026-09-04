<template>
  <div class="qa-page">
    <div class="qa-main">
      <div class="composer card">
        <div class="composer-head">
          <span>智能问答</span>
          <a-button type="link" @click="draft = ''">清空</a-button>
        </div>
        <a-textarea v-model:value="draft" :rows="4" placeholder="请输入问题，例如：请解释 RAG 的工作原理并举例说明其优势" />
        <div class="composer-actions">
          <a-space>
            <span class="muted">检索策略</span>
            <a-select v-model:value="searchStrategy" style="width: 180px">
              <a-select-option value="adaptive">自适应（推荐）</a-select-option>
              <a-select-option value="hybrid">混合检索</a-select-option>
              <a-select-option value="vector">向量检索</a-select-option>
              <a-select-option value="keyword">关键词检索</a-select-option>
            </a-select>
            <a-select v-model:value="kbId" allow-clear placeholder="高级设置 · 知识库" style="width: 200px">
              <a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option>
            </a-select>
          </a-space>
          <a-button type="primary" :loading="loading" @click="ask(draft)">开始检索</a-button>
        </div>
      </div>

      <div class="card tabs-card">
        <a-tabs v-model:activeKey="tab">
          <a-tab-pane key="answer" tab="回答">
            <div v-if="turns.length">
              <div v-for="turn in turns" :key="turn.trace_id || turn.id" class="turn">
                <div class="q">{{ turn.query }}</div>
                <pre class="answer">{{ turn.answer }}</pre>
              </div>
              <div v-if="result" class="toolbar">
                <a-space>
                  <a-button type="text" @click="feedback = 'up'">👍</a-button>
                  <a-button type="text" @click="feedback = 'down'">👎</a-button>
                  <a-button type="text" @click="copyAnswer">复制</a-button>
                  <span class="muted">耗时 {{ ((result.elapsed_ms || 0) / 1000).toFixed(2) }}s · {{ result.tokens || 0 }} tokens</span>
                </a-space>
                <a-button type="link" @click="showRaw = !showRaw">{{ showRaw ? "收起原始输出" : "展开原始输出" }}</a-button>
              </div>
              <pre v-if="showRaw && result" class="raw">{{ JSON.stringify(result, null, 2) }}</pre>
            </div>
            <a-empty v-else description="输入问题后开始检索" />
          </a-tab-pane>
          <a-tab-pane key="process" tab="检索过程">
            <div v-if="result" class="process">
              <div class="step">问题分析 · {{ result.understanding.intent }} / {{ (result.understanding.topics || []).join(", ") }}</div>
              <div class="step">检索规划 · {{ (result.plan.required_roles || []).join(" → ") }}</div>
              <div class="step">混合检索 · Keyword {{ result.retrieval.keyword }} / Vector {{ result.retrieval.vector }} / Graph {{ result.retrieval.graph }}</div>
              <div class="step">Rerank · Top {{ result.retrieval.reranked }}</div>
              <div class="step">完整性 · {{ Math.round((result.completeness.completeness_score || 0) * 100) }}%</div>
            </div>
            <a-empty v-else description="暂无检索过程" />
          </a-tab-pane>
          <a-tab-pane key="hits" :tab="`检索结果 (${(result?.hits || []).length})`">
            <a-list :data-source="result?.hits || []">
              <template #renderItem="{ item }">
                <a-list-item>
                  <a-list-item-meta :title="item.title" :description="`${item.semantic_role} · ${item.source_chapter || ''} p.${item.source_page || ''}`" />
                </a-list-item>
              </template>
            </a-list>
          </a-tab-pane>
          <a-tab-pane key="cites" :tab="`引用来源 (${(result?.citations || []).length})`">
            <a-list size="small" :data-source="result?.citations || []">
              <template #renderItem="{ item }">
                <a-list-item>{{ item.title }} · {{ item.chapter }} p.{{ item.page }}</a-list-item>
              </template>
            </a-list>
          </a-tab-pane>
        </a-tabs>
      </div>

      <div class="bottom-row">
        <div class="history card">
          <div class="history-head">
            <b>会话历史</b>
            <a-button type="link" @click="clearSessions">清空</a-button>
          </div>
          <div class="history-list">
            <button
              v-for="item in sessions"
              :key="item.id"
              type="button"
              class="history-item"
              :class="{ active: item.id === sessionId }"
              @click="openSession(item.id)"
            >
              <span>{{ item.title }}</span>
              <span class="muted">{{ item.time }}</span>
            </button>
            <a-empty v-if="!sessions.length" description="暂无会话" />
          </div>
          <a-button block class="new-session" @click="newSession">+ 新建会话</a-button>
        </div>
        <div class="follow card">
          <a-input-search
            v-model:value="followup"
            placeholder="继续提问..."
            enter-button="发送"
            :loading="loading"
            @search="askFollowup"
          />
        </div>
      </div>
    </div>

    <aside class="qa-side">
      <div class="card">
        <div class="side-title">
          <span>自适应策略</span>
          <a-tag :color="result ? 'blue' : 'default'">{{ result ? "运行中" : "待检索" }}</a-tag>
        </div>
        <div class="flow">
          <div>
            <b>问题分析</b>
            <p>类型：{{ intentLabel }} · 复杂度：{{ complexity }}</p>
          </div>
          <div>
            <b>检索策略</b>
            <p>{{ strategyLabel }} · 权重 0.7 / 0.3</p>
          </div>
          <div>
            <b>重排策略</b>
            <p>Cross-Encoder · Top K：{{ result?.retrieval?.reranked || 8 }}</p>
          </div>
          <div>
            <b>生成策略</b>
            <p>LLM：{{ result?.model || "gpt-4o-mini" }} · Temperature 0.2</p>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="side-title">检索效果评估</div>
        <div class="score">
          <strong>{{ evalScore }}</strong>
          <span>{{ evalDelta }}</span>
        </div>
        <div class="metric"><span>相关性</span><a-progress :percent="evalBars.relevance" size="small" /></div>
        <div class="metric"><span>忠实度</span><a-progress :percent="evalBars.faithfulness" size="small" /></div>
        <div class="metric"><span>完整度</span><a-progress :percent="evalBars.completeness" size="small" /></div>
      </div>
      <div class="card">
        <div class="side-title">知识库状态</div>
        <div v-for="kb in kbs" :key="kb.id" class="kb-row">
          <div>
            <b>{{ kb.name }}</b>
            <p class="muted">文档 {{ kb.document_count }} · 知识单元 {{ kb.unit_count }}</p>
          </div>
          <a-tag color="green">正常</a-tag>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { message } from "ant-design-vue";
import { api } from "../api";

const draft = ref("请问如何解决 CDC 中的亚稳态问题？");
const followup = ref("");
const kbId = ref<string | undefined>();
const kbs = ref<any[]>([]);
const searchStrategy = ref("adaptive");
const loading = ref(false);
const result = ref<any>(null);
const turns = ref<any[]>([]);
const sessions = ref<any[]>([]);
const sessionId = ref<string | undefined>();
const tab = ref("answer");
const showRaw = ref(false);
const feedback = ref("");

const intentLabel = computed(() => result.value?.understanding?.intent || "知识问答");
const complexity = computed(() => {
  const risk = result.value?.understanding?.risk;
  if (risk === "high") return "高";
  if (risk === "low") return "低";
  return "中";
});
const strategyLabel = computed(() => {
  const map: Record<string, string> = {
    adaptive: "自适应 · 向量 + 关键词",
    hybrid: "混合检索",
    vector: "向量检索",
    keyword: "关键词检索",
  };
  return map[searchStrategy.value];
});
const evalBars = computed(() => ({
  relevance: Math.round((result.value?.confidence?.retrieval_relevance || 0.8) * 100),
  faithfulness: Math.round((result.value?.confidence?.ai_confidence || 0.75) * 100),
  completeness: Math.round((result.value?.completeness?.completeness_score || result.value?.confidence?.completeness || 0.78) * 100),
}));
const evalScore = computed(() => (result.value?.confidence?.final ?? 0.82).toFixed(2));
const evalDelta = computed(() => {
  const level = result.value?.confidence?.level;
  return level === "high" ? "较昨日 +6.2%" : "等待评估";
});

async function loadSessions() {
  sessions.value = (await api.get("/chat/sessions")).data;
}

async function loadKbs() {
  kbs.value = (await api.get("/knowledge-bases")).data;
  kbId.value = kbId.value || kbs.value[0]?.id;
}

async function ask(text: string) {
  const query = text.trim();
  if (!query) return;
  loading.value = true;
  try {
    const { data } = await api.post("/chat", {
      query,
      kb_id: kbId.value,
      session_id: sessionId.value,
      search_strategy: searchStrategy.value,
    });
    result.value = data;
    sessionId.value = data.session_id;
    turns.value = [...turns.value, { ...data, query }];
    tab.value = "answer";
    await loadSessions();
  } finally {
    loading.value = false;
  }
}

async function askFollowup(value: string) {
  await ask(value);
  followup.value = "";
}

async function openSession(id: string) {
  sessionId.value = id;
  const { data } = await api.get(`/chat/sessions/${id}`);
  turns.value = data.turns || [];
  result.value = data.latest;
  draft.value = data.latest?.query || "";
}

async function newSession() {
  const { data } = await api.post("/chat/sessions");
  sessionId.value = data.id;
  turns.value = [];
  result.value = null;
  draft.value = "";
  await loadSessions();
}

async function clearSessions() {
  await api.delete("/chat/sessions");
  sessionId.value = undefined;
  sessions.value = [];
  turns.value = [];
  result.value = null;
  message.success("会话已清空");
}

async function copyAnswer() {
  const text = turns.value.map((item) => item.answer).filter(Boolean).join("\n\n");
  await navigator.clipboard.writeText(text || result.value?.answer || "");
  message.success("已复制");
}

onMounted(async () => {
  await loadKbs();
  await loadSessions();
});
</script>

<style scoped>
.qa-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}
.qa-main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.qa-side { display: flex; flex-direction: column; gap: 12px; }
.card {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.composer-head, .history-head, .side-title, .composer-actions, .toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.composer-head { font-weight: 600; }
.composer-actions { margin-top: 12px; }
.tabs-card { min-height: 280px; }
.turn { margin-bottom: 16px; }
.q { color: #2563eb; margin-bottom: 8px; font-weight: 600; }
.answer, .raw { white-space: pre-wrap; font-family: inherit; }
.raw { background: #f8fafc; padding: 12px; max-height: 240px; overflow: auto; }
.muted { color: #6b7280; font-size: 12px; }
.process .step { padding: 8px 0; border-bottom: 1px solid #f3f4f6; }
.bottom-row { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 12px; }
.history { display: flex; flex-direction: column; min-height: 220px; }
.history-list { flex: 1; overflow: auto; }
.history-item {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  border: 0;
  background: transparent;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
}
.history-item.active { background: #eff6ff; color: #1d4ed8; }
.new-session { margin-top: 8px; color: #2563eb; border-color: #bfdbfe; }
.follow { display: flex; align-items: center; }
.flow > div { padding: 8px 0; border-bottom: 1px solid #f3f4f6; }
.flow p { margin: 4px 0 0; color: #6b7280; font-size: 12px; }
.score { display: flex; align-items: baseline; gap: 8px; margin: 8px 0 12px; }
.score strong { font-size: 32px; color: #2563eb; }
.metric { margin-bottom: 6px; }
.kb-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #f3f4f6; }
.kb-row p { margin: 2px 0 0; }
@media (max-width: 1100px) {
  .qa-page, .bottom-row { grid-template-columns: 1fr; }
}
</style>
