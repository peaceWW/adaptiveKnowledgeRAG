<template>
  <div class="qa-page">
    <aside class="history-panel" :class="{ 'mobile-open': showHistory }">
      <div class="panel-heading"><b>会话历史</b><a-button type="text" class="mobile-toggle" @click="showHistory = false">关闭</a-button></div>
      <a-button type="primary" block :disabled="busy" @click="newSession">＋ 新建会话</a-button>
      <div class="history-list">
        <button v-for="item in sessions" :key="item.id" class="history-item" :class="{ active: sessionId === item.id }" :disabled="busy" @click="openSession(item.id)">
          <span>{{ item.title }}</span><small>{{ item.time }}</small>
        </button>
        <a-empty v-if="!sessions.length" description="你的对话将保存在这里" :image="undefined" />
      </div>
      <a-popconfirm title="确定清空所有会话？此操作无法撤销。" @confirm="clearSessions"><a-button type="text" :disabled="busy || !sessions.length">清空会话历史</a-button></a-popconfirm>
    </aside>
    <section class="chat-panel">
      <header class="chat-heading">
        <div><a-button class="mobile-toggle" @click="showHistory = !showHistory">会话</a-button><b>智能问答</b><span class="subtitle">基于知识库，找到有依据的答案</span></div>
        <a-tag :color="loading ? 'processing' : 'default'">{{ loading ? stageLabel : '知识库助手' }}</a-tag>
      </header>
      <div ref="scrollArea" class="conversation" @scroll="trackScroll">
        <div v-if="!turns.length" class="welcome"><div class="welcome-icon">✦</div><h1>有什么知识问题想了解？</h1><p>选择知识库开始提问，回答会附上相关来源和图片。</p><div class="suggestions"><button v-for="q in suggestions" :key="q" @click="draft = q">{{ q }} ↗</button></div></div>
        <article v-for="(turn, index) in turns" :key="turn.id || index" class="turn">
          <div class="question"><span>{{ turn.query }}</span></div>
          <div class="assistant-label">✦ 知识库助手 <small v-if="turn.pending">{{ stageLabel }}</small></div>
          <div v-if="turn.answer" class="answer markdown-body" v-html="renderAnswer(turn.answer)"></div>
          <div v-else-if="turn.pending" class="thinking"><a-spin size="small" /> {{ stageLabel }}…</div>
          <a-alert v-if="turn.error" :message="turn.error" type="warning" show-icon />
          <div v-if="figures(turn).length" class="figures"><h4>相关图片 <small>点击图片可放大</small></h4><div class="figure-grid"><figure v-for="(cite, ci) in figures(turn)" :key="ci"><DocumentAsset :document-id="cite.document_id || ''" :image-key="cite.image_key" :image-url="cite.image_key ? undefined : cite.image_url" :alt="cite.title || '知识库图片'" /><figcaption>{{ cite.title }} <small v-if="cite.page">· 第 {{ cite.page }} 页</small></figcaption></figure></div></div>
          <details v-if="turn.citations?.length" class="sources"><summary>引用来源 · {{ turn.citations.length }}</summary><div v-for="(cite, ci) in turn.citations" :key="ci" class="source"><b>{{ Number(ci) + 1 }}. {{ cite.title }}</b><small>{{ cite.document_title }} {{ cite.chapter }} {{ cite.section }} <template v-if="cite.page">· 第 {{ cite.page }} 页</template></small><small v-if="cite.doi">DOI：{{ cite.doi }}</small></div></details>
          <details v-if="turn.understanding || turn.hits?.length" class="sources"><summary>检索详情与评估</summary><div class="metadata"><p>问题类型：{{ turn.understanding?.intent || '分析中' }}</p><p>检索命中：向量 {{ turn.retrieval?.vector ?? '—' }} · 关键词 {{ turn.retrieval?.keyword ?? '—' }} · 重排 {{ turn.retrieval?.reranked ?? '—' }}</p><p>完整度：{{ percent(turn.completeness?.completeness_score) }} · 综合置信度：{{ percent(turn.confidence?.final) }}</p><ul><li v-for="hit in turn.hits || []" :key="hit.id">{{ hit.title }} <small>{{ hit.source_chapter }} {{ hit.source_page ? `· 第 ${hit.source_page} 页` : '' }}</small></li></ul></div></details>
          <div v-if="!turn.pending" class="turn-actions"><a-button size="small" type="text" @click="copyAnswer(turn.answer)">复制回答</a-button><a-button v-if="turn.error" size="small" type="text" :disabled="busy" @click="draft = turn.query">重新编辑问题</a-button><small v-if="turn.elapsed_ms">{{ (turn.elapsed_ms / 1000).toFixed(1) }} 秒</small></div>
        </article>
      </div>
      <footer class="composer">
        <button v-if="!atBottom && turns.length" class="jump-latest" @click="scrollBottom">↓ 回到最新回答</button>
        <div class="settings"><a-select v-model:value="kbId" allow-clear placeholder="全部可用知识库" :disabled="busy" aria-label="选择知识库"><a-select-option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</a-select-option></a-select><span>自适应检索</span></div>
        <div class="input-box"><a-textarea v-model:value="draft" :auto-size="{ minRows: 2, maxRows: 6 }" :disabled="switching" :placeholder="turns.length ? '继续提问，例如：这个约束在什么工艺角下成立？' : '输入设计问题，例如：RX 什么时候使用 ADC？嵌入式 FFE 如何降低量化噪声？'" @keydown="onKeydown" /><div class="input-footer"><small>Enter 发送 · Shift + Enter 换行</small><a-button v-if="loading" @click="stop">停止生成</a-button><a-button v-else type="primary" :disabled="busy || !draft.trim()" @click="ask">发送 ↑</a-button></div></div>
        <p class="composer-note">回答基于知识库内容生成，请结合引用来源核对。</p>
      </footer>
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { message } from 'ant-design-vue';
import { useRoute } from 'vue-router';
import { api } from '../api';
import { streamChat } from '../chatStream';
import { renderAnswer } from '../answer';
import DocumentAsset from '../components/DocumentAsset.vue';
const route = useRoute();
const draft = ref(typeof route.query.question === 'string' ? route.query.question : ''), kbId = ref<string>(), kbs = ref<any[]>([]), sessions = ref<any[]>([]), turns = ref<any[]>([]), sessionId = ref<string>();
const loading = ref(false), switching = ref(false), showHistory = ref(false), stage = ref('understand'), scrollArea = ref<HTMLElement>(), atBottom = ref(true);
const busy = computed(() => loading.value || switching.value);
const stageLabel = computed(() => ({ understand: '正在理解问题', plan: '正在规划检索', retrieve: '正在检索知识', complete: '正在核对完整性', answer: '正在生成回答' }[stage.value] || '正在处理'));
const suggestions = ['请概括知识库中的主要内容', '请解释 RAG 的工作原理', '如何解决 CDC 中的亚稳态问题？'];
let controller: AbortController | undefined;
const percent = (value: unknown) => typeof value === 'number' ? `${Math.round(value * 100)}%` : '暂无';
function figures(turn: any) { return (turn.citations || []).filter((c: any) => c.image_key || c.image_url); }
function trackScroll() { const el = scrollArea.value; if (el) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }
async function scrollBottom() { await nextTick(); const el = scrollArea.value; if (el) el.scrollTop = el.scrollHeight; atBottom.value = true; }
async function loadSessions() { sessions.value = (await api.get('/chat/sessions')).data; }
async function ask() {
  const query = draft.value.trim(); if (!query || busy.value) return;
  draft.value = ''; loading.value = true; stage.value = 'understand'; controller = new AbortController();
  const turn = { query, answer: '', citations: [], pending: true, error: '' };
  turns.value.push(turn); const current = turns.value[turns.value.length - 1];
  await scrollBottom();
  try {
    await streamChat({ query, kb_id: kbId.value, session_id: sessionId.value, search_strategy: 'adaptive' }, controller.signal, (event, data) => {
      if (event === 'session') sessionId.value = data.session_id;
      if (event === 'status') stage.value = data.stage;
      if (event === 'delta') current.answer += data.text;
      if (event === 'metadata' || event === 'citations' || event === 'done') Object.assign(current, data);
      if (atBottom.value) void scrollBottom();
    });
  } catch (error: any) { current.error = error.name === 'AbortError' ? '已停止生成，当前内容可能不完整。' : error.message || '请求失败，请重试。'; }
  finally { current.pending = false; loading.value = false; controller = undefined; await loadSessions().catch(() => {}); }
}
function stop() { controller?.abort(); }
function onKeydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void ask(); } }
async function openSession(id: string) {
  if (busy.value) return; switching.value = true;
  try { const { data } = await api.get(`/chat/sessions/${id}`); sessionId.value = id; turns.value = data.turns || []; draft.value = ''; showHistory.value = false; await scrollBottom(); }
  finally { switching.value = false; }
}
function newSession() { if (busy.value) return; sessionId.value = undefined; turns.value = []; draft.value = ''; showHistory.value = false; }
async function clearSessions() { if (busy.value) return; switching.value = true; try { await api.delete('/chat/sessions'); sessions.value = []; sessionId.value = undefined; turns.value = []; } finally { switching.value = false; } }
async function copyAnswer(text: string) { try { await navigator.clipboard.writeText(text || ''); message.success('已复制'); } catch { message.error('复制失败，请手动选择文字复制'); } }
onMounted(async () => { await Promise.allSettled([loadSessions(), api.get('/knowledge-bases').then(({ data }) => { kbs.value = data; kbId.value = data.some((kb: any) => kb.id === route.query.kb_id) ? String(route.query.kb_id) : data[0]?.id; })]); });
onBeforeUnmount(stop);
</script>
<style scoped>
.qa-page{display:grid;grid-template-columns:240px minmax(0,1fr);height:calc(100dvh - 116px);min-height:560px;gap:0;border:1px solid #e5eaf2;border-radius:16px;overflow:hidden;background:white}
.history-panel{display:flex;flex-direction:column;gap:16px;padding:20px 14px;background:#f8fafc;border-right:1px solid #e5eaf2;min-height:0}.panel-heading{display:flex;justify-content:space-between;align-items:center;padding:0 8px}.history-list{flex:1;overflow:auto}.history-item{display:flex;flex-direction:column;gap:6px;width:100%;padding:13px 12px;border:0;border-radius:8px;background:transparent;text-align:left;cursor:pointer;margin-bottom:4px}.history-item span{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;width:100%;font-size:13px}.history-item:hover{background:#edf2fa}.history-item.active{background:#e8efff;color:#2454cf}small{color:#8792a4;font-size:12px}.chat-panel{display:flex;flex-direction:column;min-width:0;min-height:0}.chat-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 26px;border-bottom:1px solid #eef1f6}.subtitle{font-size:12px;color:#8792a4;margin-left:16px}.conversation{flex:1;overflow:auto;padding:28px max(24px,calc((100% - 880px)/2));scroll-behavior:auto;overscroll-behavior:contain}.welcome{text-align:center;padding:9vh 0 40px}.welcome-icon{display:inline-grid;place-items:center;width:58px;height:58px;border-radius:18px;background:#eef3ff;color:#3f64e8;font-size:32px}.welcome h1{font-size:26px;margin:20px 0 12px}.welcome p{color:#8792a4}.suggestions{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:28px}.suggestions button{border:1px solid #e5eaf2;background:white;padding:12px 16px;border-radius:10px;color:#526078;cursor:pointer}.turn{margin-bottom:36px}.question{display:flex;justify-content:flex-end;margin-bottom:25px}.question span{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf2ff;border-radius:14px 14px 4px 14px;padding:12px 18px;max-width:85%;font-size:15px}.assistant-label{font-weight:600;color:#4265cf;margin-bottom:14px}.assistant-label small{margin-left:10px;font-weight:400}.answer{font-size:15px;line-height:1.85;color:#263449;overflow-wrap:anywhere}.answer :deep(p){margin:0 0 14px}.answer :deep(h1),.answer :deep(h2),.answer :deep(h3){font-size:19px;margin:24px 0 12px}.answer :deep(pre){background:#f5f7fb;padding:16px;border-radius:8px;overflow:auto;line-height:1.6}.answer :deep(code){background:#f1f4f9;padding:2px 4px;border-radius:4px}.answer :deep(table){display:block;max-width:100%;overflow:auto;border-collapse:collapse;margin:16px 0}.answer :deep(th),.answer :deep(td){border:1px solid #dde4ef;padding:8px 12px}.answer :deep(th){background:#f7f9fc}.answer :deep(blockquote){border-left:3px solid #b5c8ff;margin-left:0;padding-left:16px;color:#64748b}.answer :deep(img){max-width:100%;max-height:480px;object-fit:contain}.answer :deep(.katex-display){overflow-x:auto;overflow-y:hidden}.thinking{display:flex;gap:12px;color:#8792a4;padding:12px 0}.sources{margin-top:12px;border:1px solid #e9edf4;border-radius:8px;padding:10px 14px}.sources summary{cursor:pointer;color:#66758b;font-size:13px}.source{display:flex;flex-direction:column;gap:4px;padding:12px 0;border-top:1px solid #f0f2f6;font-size:13px}.metadata{font-size:13px;padding-top:12px}.metadata li{margin:6px 0}.turn-actions{display:flex;align-items:center;gap:12px;margin-top:12px}.figures{margin-top:20px}.figures h4 small{font-weight:400;margin-left:10px}.figure-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.figure-grid figure{margin:0;min-width:0}.figure-grid :deep(.asset-url){display:none}.figure-grid :deep(.asset-frame){margin:0 0 8px}.figure-grid figcaption{font-size:12px;color:#65738a}.composer{position:relative;padding:12px max(24px,calc((100% - 880px)/2)) 10px;background:white;border-top:1px solid #f1f4f8}.settings{display:flex;align-items:center;gap:12px;margin-bottom:10px;font-size:12px;color:#8b95a6}.settings .ant-select{min-width:200px;max-width:75%}.input-box{border:1px solid #dce3ef;border-radius:12px;padding:10px 12px;box-shadow:0 4px 18px #233d7510}.input-box:focus-within{border-color:#91adf7}.input-box :deep(textarea){border:0;box-shadow:none!important;resize:none;font-size:14px}.input-footer{display:flex;justify-content:space-between;align-items:center;padding-top:6px}.composer-note{text-align:center;font-size:11px;color:#9aa4b4;margin:8px 0 0}.jump-latest{position:absolute;top:-38px;left:50%;transform:translateX(-50%);background:white;border:1px solid #dce3ef;border-radius:18px;padding:5px 14px;cursor:pointer;color:#526078}.mobile-toggle{display:none}
@media(max-width:1100px){.qa-page{grid-template-columns:200px minmax(0,1fr)}.subtitle{display:none}.conversation{padding:24px}.composer{padding:12px 24px}}
@media(max-width:760px){.qa-page{grid-template-columns:1fr;height:calc(100dvh - 170px);position:relative;min-height:480px}.history-panel{display:none}.history-panel.mobile-open{display:flex;position:absolute;inset:0 auto 0 0;width:260px;z-index:10;box-shadow:10px 0 35px #26344920}.mobile-toggle{display:inline-block;margin-right:8px}.chat-heading{padding:12px}.conversation{padding:18px}.composer{padding:10px 14px}.welcome h1{font-size:22px}.input-footer small{font-size:10px}}
</style>
