<template>
  <div class="index-maintenance">
    <a-alert type="info" show-icon message="当资料找不到时，先检查可检索知识点数量，再补充文档关键词。" description="这里维护文档辅助标签与元数据；补全标签不会重新抽取文档，也不会重建知识向量。" />
    <div class="maintenance-grid">
      <aside class="documents-pane">
        <h3>选择需要检查的文档</h3>
        <a-select v-model:value="kbId" allow-clear placeholder="全部知识库" :options="kbs.map(k => ({ value: k.id, label: k.name }))" :disabled="busy || dirty" @change="loadList" />
        <a-input-search v-model:value="query" allow-clear placeholder="搜索文件名或关键词" :disabled="busy || dirty" @search="loadList" />
        <a-spin :spinning="listLoading"><button v-for="doc in docs" :key="doc.id" class="document-row" :class="{ selected: selectedId === doc.id }" :disabled="busy" @click="choose(doc.id)"><b>{{ doc.filename }}</b><small>{{ doc.retrievable_count ?? 0 }} 个可检索知识点 · {{ doc.keyword_count }} 个标签</small><a-tag :color="doc.retrievable_count ? 'green' : 'orange'">{{ doc.retrievable_count ? '已收录知识' : '尚无可检索知识' }}</a-tag></button><a-empty v-if="!docs.length && !listLoading" description="当前范围没有文档" /></a-spin>
      </aside>
      <section class="maintenance-editor" :aria-busy="busy">
        <template v-if="current">
          <div class="editor-header"><div><h3>{{ current.filename }}</h3><p>{{ current.unit_count }} 个知识点 · {{ dirty ? '有未保存修改' : '已加载保存内容' }}</p></div><a-button :disabled="busy" @click="$emit('test', current.kb_id)">返回检索验证</a-button></div>
          <a-alert v-if="selectedSummary && !selectedSummary.retrievable_count" type="warning" show-icon message="该文档尚无可检索知识点" description="请到文档管理检查抽取结果和知识状态；仅添加标签无法补足知识内容。" />
          <div class="keyword-heading"><h4>文档关键词</h4><span>补充缩写、全称、模块名，帮助检索定位文档</span></div>
          <div class="add-keyword"><a-input v-model:value="newKeyword" placeholder="例如：SAR ADC、逐次逼近、接收判决链" :disabled="busy" @pressEnter="addKeyword" /><a-button :disabled="busy || !newKeyword.trim()" @click="addKeyword">添加标签</a-button></div>
          <div class="keyword-tags"><a-tag v-for="(item, index) in keywords" :key="index" :closable="!busy" @close.prevent="keywords.splice(index, 1)">{{ item.keyword }}</a-tag><span v-if="!keywords.length">暂无关键词，可手动添加或使用“补全并同步标签”。</span></div>
          <details class="metadata-editor"><summary>高级：文档元数据 <small>标题、DOI 等字段</small></summary><p>保留原有字段类型；修改后会更新文档索引信息。</p><a-textarea v-model:value="metadataText" :rows="12" :disabled="busy" aria-label="文档元数据 JSON" /></details>
          <div class="save-actions"><a-button type="primary" :loading="busy" :disabled="!dirty" @click="save">保存修改</a-button><a-button :disabled="busy || !dirty" @click="apply(current)">撤销未保存修改</a-button><a-button :disabled="busy || dirty" @click="rebuild">补全并同步标签</a-button></div>
          <p class="save-note">补全操作保留人工与模型生成的标签；手动修改需先保存。标签数量不代表检索命中率。</p>
          <details class="danger-zone"><summary>更多维护操作</summary><p>清空关键词和元数据不会删除文档或知识点，也不会将文档从问答检索中移除。</p><a-popconfirm title="清空该文档所有关键词和元数据？此操作无法撤销。" @confirm="clear"><a-button danger :disabled="busy || dirty">清空辅助索引</a-button></a-popconfirm></details>
        </template>
        <a-empty v-else description="选择文档，检查它是否已收录以及哪些关键词可以检索到它" />
      </section>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { Modal, message } from 'ant-design-vue';
import { api } from '../api';
const props = defineProps<{ kbs: any[]; documentId?: string; initialKb?: string }>();
defineEmits<{ test: [kbId: string] }>();
const kbId = ref<string>(), query = ref(''), docs = ref<any[]>([]), selectedId = ref(''), current = ref<any>(), keywords = ref<any[]>([]), metadataText = ref('{}'), newKeyword = ref(''), busy = ref(false), listLoading = ref(false), saved = ref('');
let version = 0, controller: AbortController | undefined;
const snapshot = computed(() => JSON.stringify({ keywords: keywords.value, metadata: metadataText.value }));
const dirty = computed(() => Boolean(current.value) && snapshot.value !== saved.value);
const selectedSummary = computed(() => docs.value.find(d => d.id === selectedId.value));
function apply(data: any) { current.value = data; selectedId.value = data.id; keywords.value = JSON.parse(JSON.stringify(data.keywords || [])); metadataText.value = JSON.stringify(data.metadata || {}, null, 2); saved.value = snapshot.value; newKeyword.value = ''; }
function mayDiscard(): Promise<boolean> { return dirty.value ? new Promise(resolve => Modal.confirm({ title: '有未保存的标签修改', content: '离开将丢弃这些修改。', okText: '丢弃并继续', cancelText: '继续编辑', onOk: () => resolve(true), onCancel: () => resolve(false) })) : Promise.resolve(true); }
async function loadList() {
  listLoading.value = true;
  try { docs.value = (await api.get('/retrieval/indexes', { params: { kb_id: kbId.value, q: query.value } })).data; if (current.value && !docs.value.some(d => d.id === selectedId.value)) { current.value = undefined; selectedId.value = ''; } }
  finally { listLoading.value = false; }
}
async function choose(id: string) {
  if (busy.value || !(await mayDiscard())) return;
  const request = ++version; controller?.abort(); controller = new AbortController(); busy.value = true;
  try { const { data } = await api.get(`/retrieval/indexes/${id}`, { signal: controller.signal }); if (request === version) apply(data); }
  finally { if (request === version) busy.value = false; }
}
function addKeyword() { const keyword = newKeyword.value.trim(); if (!keyword) return; if (keywords.value.some(k => k.keyword.toLowerCase() === keyword.toLowerCase())) { message.info('标签已存在'); return; } keywords.value.push({ keyword, weight: 1, source: 'manual' }); newKeyword.value = ''; }
async function save() {
  let metadata: any;
  try { metadata = JSON.parse(metadataText.value); if (!metadata || Array.isArray(metadata) || typeof metadata !== 'object') throw new Error(); }
  catch { message.error('元数据必须是有效的 JSON 对象，请检查后再保存'); return; }
  busy.value = true;
  try { const { data } = await api.put(`/retrieval/indexes/${selectedId.value}`, { keywords: keywords.value, metadata }); apply(data); await loadList(); message.success('标签已保存，可重新验证检索结果'); }
  finally { busy.value = false; }
}
async function rebuild() { busy.value = true; try { apply((await api.post(`/retrieval/indexes/${selectedId.value}/reindex`)).data); await loadList(); message.success('已补全并同步文档标签'); } finally { busy.value = false; } }
async function clear() { busy.value = true; try { await api.delete(`/retrieval/indexes/${selectedId.value}`); apply({ ...current.value, keywords: [], metadata: {} }); await loadList(); message.success('辅助索引已清空'); } finally { busy.value = false; } }
async function openRequested() { if (!(await mayDiscard())) return; kbId.value = props.initialKb || undefined; query.value = ''; await loadList(); if (props.documentId && docs.value.some(d => d.id === props.documentId)) { saved.value = snapshot.value; await choose(props.documentId); } }
watch(() => [props.documentId, props.initialKb], openRequested);
onMounted(openRequested); onBeforeRouteLeave(mayDiscard); onBeforeUnmount(() => { version++; controller?.abort(); });
</script>
<style scoped>
.maintenance-grid{display:grid;grid-template-columns:280px minmax(0,1fr);gap:16px;margin-top:16px}.documents-pane,.maintenance-editor{background:white;border:1px solid #e3e9f3;border-radius:12px;padding:20px;min-width:0}.documents-pane{max-height:740px;overflow:auto}.documents-pane>.ant-select,.documents-pane>.ant-input-search{width:100%;margin-bottom:12px}.documents-pane h3{font-size:14px;margin:0 0 16px}.document-row{display:flex;flex-direction:column;gap:8px;text-align:left;width:100%;border:0;border-radius:8px;background:transparent;padding:12px;margin-bottom:6px;cursor:pointer}.document-row.selected{background:#edf3ff}.document-row b{font-size:12px;overflow-wrap:anywhere;line-height:1.7}.document-row small{font-size:11px;color:#8090a6}.document-row .ant-tag{align-self:flex-start}.editor-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:20px}.editor-header h3{font-size:17px;margin:0;overflow-wrap:anywhere}.editor-header p{color:#8390a4;font-size:12px;margin:8px 0}.keyword-heading{margin-top:24px}.keyword-heading h4{margin:0 0 6px}.keyword-heading span,.save-note{font-size:12px;color:#8a97aa}.add-keyword{display:flex;gap:8px;margin:12px 0}.keyword-tags{display:flex;flex-wrap:wrap;gap:8px;min-height:65px;padding:12px;background:#f7f9fd;border-radius:8px}.keyword-tags .ant-tag{height:26px;line-height:24px;margin:0}.keyword-tags>span{color:#8a97aa;font-size:12px}.metadata-editor{margin:22px 0;border:1px solid #e5eaf3;border-radius:8px;padding:12px}.metadata-editor summary{cursor:pointer;font-size:13px}.metadata-editor small,.metadata-editor p,.danger-zone p{font-size:12px;color:#8a97aa;line-height:1.8}.metadata-editor textarea{font-family:monospace}.save-actions{display:flex;gap:10px;flex-wrap:wrap}.danger-zone{border-top:1px solid #eef1f7;margin-top:24px;padding-top:16px}.danger-zone summary{cursor:pointer;font-size:12px;color:#8490a3}@media(max-width:900px){.maintenance-grid{grid-template-columns:1fr}.documents-pane{max-height:350px}.editor-header{flex-direction:column}}
</style>
