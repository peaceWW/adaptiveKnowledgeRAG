<template>
  <div class="design-page">
    <header class="design-header">
      <div><div class="eyebrow">CHIP DESIGN KNOWLEDGE</div><h2>芯片设计知识图谱</h2><p>从模块找到技术，从技术回到依据。</p></div>
      <div class="header-actions"><a-select v-model:value="kbId" :options="[{ value: '', label: '全部可用知识库' }, ...kbs.map(k => ({ value: k.id, label: k.name }))]" aria-label="知识库范围" @change="load" /><a-button :loading="loading" @click="load">刷新知识体系</a-button><a-button :disabled="!nodes.length" @click="exportOutline">导出大纲</a-button></div>
    </header>
    <div class="summary-row"><span><b>{{ summary.documents || 0 }}</b> 来源文档</span><span><b>{{ summary.modules || 0 }}</b> 已覆盖模块</span><span><b>{{ summary.technologies || 0 }}</b> 候选技术</span><span><b>{{ summary.units || 0 }}</b> 知识点</span><small>跨文档归并 · 刷新即可纳入新增知识</small></div>
    <a-alert v-if="error" type="error" :message="error" show-icon class="load-error" />
    <div v-if="loading && !nodes.length" class="initial-loading"><a-spin /><p>正在按芯片设计模块整理知识…</p></div>
    <div v-else class="design-workspace" :aria-busy="loading">
      <aside class="outline-panel">
        <div class="panel-title">知识体系 <small>{{ nodes.length }} 个节点</small></div>
        <a-input-search v-model:value="keyword" allow-clear placeholder="搜索模块、技术或文档" aria-label="搜索知识体系" @search="selectFirstMatch" />
        <div class="outline-actions"><button @click="expandOutline">展开全部</button><button @click="expandedKeys = ['chip', 'architecture', 'modules']">收起层级</button></div>
        <div class="outline-scroll"><a-tree :tree-data="treeData" :expanded-keys="expandedKeys" :selected-keys="[selectedId]" block-node show-line @expand="(keys: (string | number)[]) => expandedKeys = keys.map(String)" @select="(keys: (string | number)[]) => keys[0] && selectNode(String(keys[0]))"><template #title="node"><span :class="{ 'search-hit': matches.has(node.key) }" :title="node.title">{{ node.title }}</span><small class="node-count">{{ byId.get(node.key)?.unit_count || 0 }}</small></template></a-tree><a-empty v-if="keyword && !treeData.length" description="没有匹配结果，请尝试模块名称或缩写" /></div>
        <div class="outline-note">目录为设计分类；数字表示知识点数量。空模块表示当前知识库尚未覆盖。</div>
      </aside>
      <section class="map-panel">
        <div class="map-heading"><b>思维导图</b><div><a-button size="small" @click="resetMap">全图</a-button><a-button size="small" :disabled="!selected" @click="focusSelection">聚焦所选</a-button><a-button size="small" @click="expandMap">展开当前分支</a-button></div></div>
        <div class="map-breadcrumb"><button v-for="id in focused?.path || []" :key="id" @click="focusId = id">{{ byId.get(id)?.name }} <span>›</span></button></div>
        <MindMap v-if="mapRoot" ref="mapRef" :root="mapRoot" :selected-id="selectedId" :collapsed="collapsed" :matches="matches" direction="horizontal" @select="selectNode" @toggle="id => collapsed[id] = !collapsed[id]" />
        <a-empty v-else description="暂无可用知识体系" />
        <div class="map-legend"><span class="legend-dot blue"></span>设计分类 <span class="legend-dot green"></span>候选技术 <span class="legend-dot purple"></span>文档与知识 <small>点击节点查看依据 · ＋ / − 展开收起 · 滚动画布浏览</small></div>
      </section>
      <aside ref="detailPanel" class="detail-panel">
        <template v-if="selected">
          <div class="detail-type">{{ kindLabels[selected.kind] }}</div><h3>{{ selected.name }}</h3>
          <p class="detail-path">{{ selected.path.map(id => byId.get(id)?.name).join(' / ') }}</p>
          <div class="detail-stats"><span>{{ selected.unit_count }} 个知识点</span><span>{{ selected.document_count }} 篇文档</span></div>
          <div v-if="!selected.unit_count" class="empty-coverage"><a-empty description="该分类尚无文档依据" /><p>上传并抽取相关文档后，刷新即可查看已收录技术。</p></div>
          <template v-else>
            <div v-if="moduleNode" class="candidates-section"><div class="section-title"><b>{{ selected.kind === 'technology' ? '同模块候选技术' : '模块候选技术' }}</b><a-button size="small" type="primary" :disabled="compareIds.length < 2" @click="showCompare = true">对比 {{ compareIds.length || '' }}</a-button></div><p class="section-hint">选择 2–4 项对比。候选项可能互补或属于不同层级，替换前需核对接口与适用条件。</p><div v-for="tech in candidateTechs" :key="tech.id" class="candidate-row" :class="{ current: selectedId === tech.id }"><a-checkbox :checked="compareIds.includes(tech.id)" :aria-label="`对比 ${tech.name}`" @change="toggleCompare(tech.id)" /><button @click="selectNode(tech.id)"><b>{{ tech.name }}</b><small>{{ tech.document_count }} 篇文档 · {{ tech.unit_count }} 个知识点</small></button></div><p v-if="!candidateTechs.length" class="section-hint">已收录模块资料，尚未识别出明确的技术方案名称。</p></div>
            <div v-else-if="selected.children.length" class="child-section"><div class="section-title"><b>下级分类</b></div><button v-for="id in selected.children" :key="id" @click="selectNode(id)">{{ byId.get(id)?.name }}<small>{{ byId.get(id)?.unit_count }} →</small></button></div>
            <div class="section-title evidence-title"><b>知识依据</b><small>{{ selectedEvidence.length }} 条</small></div>
            <a-segmented v-model:value="evidenceFilter" :options="[{ label: '全部', value: 'all' }, { label: '指标', value: 'metrics' }, { label: '约束', value: 'constraints' }, { label: '对比', value: 'comparisons' }]" block />
            <div v-for="item in pagedEvidence" :key="item.id" class="evidence-card"><div><a-tag :color="item.lifecycle === 'AI_PROCESSED' ? 'orange' : 'blue'">{{ roleLabel(item.role) }}</a-tag><small v-if="item.lifecycle === 'AI_PROCESSED'">AI 抽取 · 待核对</small></div><button class="evidence-title-button" @click="openEvidence(item)">{{ item.title }}</button><p>{{ item.content.slice(0, 180) }}{{ item.content.length > 180 ? '…' : '' }}</p><div class="evidence-source">{{ item.document_title }}<span v-if="item.page"> · p.{{ item.page }}</span></div><button class="source-link" @click="openEvidence(item)">查看依据{{ isPdf(item) ? '与原 PDF' : '' }} ↗</button></div>
            <a-empty v-if="!filteredEvidence.length" description="暂无此类依据，不能据此推断指标或替换条件" />
            <a-pagination v-if="filteredEvidence.length > 6" v-model:current="evidencePage" simple :total="filteredEvidence.length" :page-size="6" class="evidence-pagination" />
          </template>
        </template>
      </aside>
    </div>
    <a-modal v-model:open="showCompare" title="模块技术对比" :width="1150" :footer="null">
      <p class="compare-notice">{{ moduleNode?.name }} · 以下为各技术关联知识的摘录，保留来源。相同模块不等于可直接替换；缺失的信息明确标为暂无依据。</p>
      <div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>核对项目</th><th v-for="tech in comparedTechs" :key="tech.id">{{ tech.name }}<small>{{ tech.document_count }} 篇文档</small></th></tr></thead><tbody><tr v-for="facet in compareFacets" :key="facet.key"><th>{{ facet.label }}</th><td v-for="tech in comparedTechs" :key="tech.id"><template v-if="techEvidence(tech, facet.key).length"><button v-for="item in techEvidence(tech, facet.key).slice(0, 3)" :key="item.id" class="compare-excerpt" @click="openEvidence(item)"><b>{{ item.title }}</b><p>{{ item.content.slice(0, 240) }}</p><small>{{ item.document_title }} · p.{{ item.page || '—' }} ↗</small></button><small v-if="techEvidence(tech, facet.key).length > 3">另有 {{ techEvidence(tech, facet.key).length - 3 }} 条，可在节点详情查看</small></template><span v-else class="no-evidence">暂无明确依据</span></td></tr><tr><th>替换结论</th><td v-for="tech in comparedTechs" :key="tech.id">候选技术，尚未确认可直接替换。需核对接口、速率、工艺、电源与时序条件。</td></tr></tbody></table></div>
    </a-modal>
    <a-modal v-model:open="showSource" :title="source?.title" :width="1200" :footer="null" destroy-on-close>
      <div v-if="source" class="source-modal"><div class="source-text"><div class="source-heading"><b>{{ source.document_title }}</b><p>{{ source.chapter }} {{ source.section }} · 页码 {{ source.page || '未记录' }}</p><a-tag>{{ source.lifecycle === 'AI_PROCESSED' ? 'AI 抽取内容，待核对' : source.lifecycle }}</a-tag></div><h4>{{ source.original ? '已保存的原文片段' : '知识点摘录' }}</h4><div class="source-content" v-html="renderAnswer(source.original || source.content)"></div><DocumentAsset v-if="source.image_key || source.image_url" :document-id="source.document_id || ''" :image-key="source.image_key" :image-url="source.image_key ? undefined : source.image_url" :alt="source.title" /></div><PdfSourceViewer v-if="isPdf(source) && !textOnly" :document-id="source.document_id!" :filename="source.filename" :source-page="source.page" :source-key="source.id" @show-text="textOnly = true" /></div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { message } from 'ant-design-vue';
import { api } from '../api';
import MindMap from '../components/MindMap.vue';
import PdfSourceViewer from '../components/PdfSourceViewer.vue';
import DocumentAsset from '../components/DocumentAsset.vue';
import { renderAnswer } from '../answer';
import { useSession } from '../stores/session';
interface DesignNode { id: string; name: string; kind: string; parent_id?: string; children: string[]; aliases: string[]; evidence_ids: string[]; path: string[]; unit_count: number; document_count: number; technology_ids: string[] }
interface Evidence { id: string; title: string; content: string; original: string; role: string; lifecycle: string; document_id?: string; document_title: string; filename: string; page?: number; chapter: string; section: string; image_key?: string; image_url?: string }
const nodes = ref<DesignNode[]>([]), evidence = ref<Record<string, Evidence>>({}), summary = ref<Record<string, number>>({}), kbs = ref<{id: string; name: string}[]>([]);
const kbId = ref(''), keyword = ref(''), selectedId = ref('chip'), focusId = ref('chip'), expandedKeys = ref<string[]>(['chip', 'architecture', 'modules']);
const collapsed = reactive<Record<string, boolean>>({}), loading = ref(false), error = ref(''), compareIds = ref<string[]>([]), showCompare = ref(false), showSource = ref(false), source = ref<Evidence>(), textOnly = ref(false), detailPanel = ref<HTMLElement>();
const evidenceFilter = ref('all'), evidencePage = ref(1);
const userSession = useSession();
const mapRef = ref<InstanceType<typeof MindMap>>();
let controller: AbortController | undefined, requestVersion = 0;
const kindLabels: Record<string, string> = { root: '设计知识总览', category: '知识分类', ip: 'IP 架构', module: '功能模块', technology: '候选技术', document: '架构文档', topic: '专题知识' };
const roles: Record<string, string[]> = { metrics: ['metric', 'parameter'], constraints: ['constraint', 'rule', 'limitation', 'exception', 'warning', 'requirement', 'assumption', 'root_cause', 'symptom'], comparisons: ['comparison'], principle: ['definition', 'principle', 'explanation', 'solution', 'interface', 'classification', 'best_practice'] };
const compareFacets = [{key: 'principle', label: '原理与实现'}, {key: 'metrics', label: '性能指标'}, {key: 'constraints', label: '适用条件与风险'}, {key: 'comparisons', label: '文档中的对比'}];
const byId = computed(() => new Map(nodes.value.map(n => [n.id, n])));
const selected = computed(() => byId.value.get(selectedId.value));
const focused = computed(() => byId.value.get(focusId.value));
const matches = computed(() => { const q = keyword.value.trim().toLowerCase(); return new Set(q ? nodes.value.filter(n => [n.name, ...n.aliases].some(v => v.toLowerCase().includes(q))).map(n => n.id) : []); });
const treeData = computed(() => {
  const keep = new Set<string>();
  for (const id of matches.value) for (const ancestor of byId.value.get(id)?.path || []) keep.add(ancestor);
  const make = (id: string): any => { const n = byId.value.get(id); if (!n || (keyword.value.trim() && !keep.has(id))) return null; return { key: id, title: n.name, children: n.children.map(make).filter(Boolean) }; };
  const root = make('chip'); return root ? [root] : [];
});
const mapRoot = computed(() => {
  function make(id: string): any { const n = byId.value.get(id); if (!n) return null; return { ...n, name: `${n.name} · ${n.unit_count}`, isRoot: id === focusId.value, isLeaf: !n.children.length, tone: n.kind === 'technology' ? 'green' : ['topic', 'document'].includes(n.kind) ? 'purple' : 'blue', icon: n.kind === 'technology' ? '◈' : n.kind === 'document' ? '▤' : '◇', children: n.children.map(make) }; }
  return make(focusId.value);
});
const moduleNode = computed(() => { const n = selected.value; return n?.kind === 'module' ? n : n?.kind === 'technology' ? byId.value.get(n.parent_id!) : undefined; });
const candidateTechs = computed(() => (moduleNode.value?.technology_ids || []).map(id => byId.value.get(id)!).filter(Boolean));
const comparedTechs = computed(() => compareIds.value.map(id => byId.value.get(id)!).filter(Boolean));
const selectedEvidence = computed(() => (selected.value?.evidence_ids || []).map(id => evidence.value[id]).filter(Boolean));
const filteredEvidence = computed(() => selectedEvidence.value.filter(e => evidenceFilter.value === 'all' || roles[evidenceFilter.value]?.includes(e.role)));
const pagedEvidence = computed(() => filteredEvidence.value.slice((evidencePage.value - 1) * 6, evidencePage.value * 6));
function techEvidence(tech: DesignNode, facet: string) { return tech.evidence_ids.map(id => evidence.value[id]).filter(e => e && roles[facet]?.includes(e.role)); }
function roleLabel(role: string) { return ({ definition: '定义', principle: '原理', parameter: '参数', metric: '指标', constraint: '约束', limitation: '局限', comparison: '对比', solution: '方案', interface: '结构', classification: '分类', formula: '公式', example: '示例', root_cause: '原因', exception: '例外' } as Record<string, string>)[role] || '知识点'; }
function selectNode(id: string) { selectedId.value = id; evidenceFilter.value = 'all'; evidencePage.value = 1; expandedKeys.value = [...new Set([...expandedKeys.value, ...(byId.value.get(id)?.path || [])])]; detailPanel.value?.scrollTo({ top: 0 }); }
function focusSelection() { focusId.value = selectedId.value; collapsed[selectedId.value] = false; }
function resetMap() { focusId.value = 'chip'; for (const n of nodes.value) collapsed[n.id] = !['chip', 'architecture', 'modules'].includes(n.id); void centerMap(); }
async function centerMap() { await nextTick(); requestAnimationFrame(() => mapRef.value?.focusNode(focusId.value)); }
function expandMap() { if (focused.value) { collapsed[focusId.value] = false; for (const id of focused.value.children) collapsed[id] = false; } }
function expandOutline() { expandedKeys.value = nodes.value.filter(n => n.children.length).map(n => n.id); }
function selectFirstMatch() {
  const query = keyword.value.trim().toLowerCase();
  const ranked = nodes.value.filter(n => matches.value.has(n.id)).sort((a, b) => {
    const score = (n: DesignNode) => n.name.toLowerCase() === query ? 0 : n.name.toLowerCase().includes(query) ? 1 : 2;
    return score(a) - score(b);
  });
  const id = ranked[0]?.id;
  if (id) { selectNode(id); focusId.value = byId.value.get(id)?.parent_id || id; collapsed[focusId.value] = false; }
}
function toggleCompare(id: string) { if (compareIds.value.includes(id)) compareIds.value = compareIds.value.filter(x => x !== id); else if (compareIds.value.length < 4) compareIds.value.push(id); else message.info('每次最多对比 4 项技术'); }
function isPdf(item: Evidence) { return Boolean(item.document_id && /\.pdf$/i.test(item.filename || '')); }
function openEvidence(item: Evidence) { source.value = item; textOnly.value = false; showSource.value = true; }
async function load() {
  controller?.abort(); controller = new AbortController(); const version = ++requestVersion;
  loading.value = true; error.value = ''; showCompare.value = false; showSource.value = false;
  try {
    const { data } = await api.get('/graph/design-map', { params: { kb_id: kbId.value }, signal: controller.signal });
    if (version !== requestVersion) return;
    nodes.value = data.nodes || []; evidence.value = data.evidence || {}; summary.value = data.summary || {}; kbs.value = data.knowledge_bases || [];
    selectedId.value = byId.value.has(selectedId.value) ? selectedId.value : 'chip'; compareIds.value = []; evidencePage.value = 1; resetMap();
  } catch (err: any) { if (version === requestVersion && err.code !== 'ERR_CANCELED') { error.value = '知识体系加载失败，请检查连接后刷新重试。'; nodes.value = []; evidence.value = {}; summary.value = {}; } }
  finally { if (version === requestVersion) loading.value = false; }
}
function exportOutline() {
  const lines = ['# 芯片设计知识体系', '', '同模块候选技术不代表可直接替换，需核对文档依据。', ''];
  const walk = (id: string, depth: number) => { const node = byId.value.get(id); if (!node) return; lines.push(`${'  '.repeat(depth)}- ${node.name.replace(/\n/g, ' ')}（${node.unit_count} 个知识点）`); if (!node.children.length) for (const eid of node.evidence_ids) { const e = evidence.value[eid]; lines.push(`${'  '.repeat(depth + 1)}- ${e.title} — ${e.document_title}，p.${e.page || '未记录'}`); } for (const child of node.children) walk(child, depth + 1); };
  walk('chip', 0); const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = '芯片设计知识体系.md'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
watch(() => moduleNode.value?.id, () => { compareIds.value = []; });
watch(evidenceFilter, () => evidencePage.value = 1);
watch(() => userSession.username, () => { kbId.value = ''; nodes.value = []; evidence.value = {}; summary.value = {}; kbs.value = []; void load(); });
watch(keyword, () => { if (keyword.value.trim()) { const ids = [...matches.value].flatMap(id => byId.value.get(id)?.path || []); expandedKeys.value = [...new Set(ids)]; } else { expandedKeys.value = ['chip', 'architecture', 'modules', ...(selected.value?.path || [])]; } });
watch(focusId, centerMap);
watch(collapsed, centerMap, { deep: true });
onMounted(() => { void load(); window.addEventListener('resize', centerMap); });
onBeforeUnmount(() => { requestVersion++; controller?.abort(); window.removeEventListener('resize', centerMap); });
</script>

<style scoped>
.design-page{color:#26344c}.design-header{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px}.eyebrow{font-size:10px;letter-spacing:1.8px;color:#7a8dad;margin-bottom:6px}.design-header h2{font-size:23px;margin:0}.design-header p{margin:6px 0 0;color:#8090a6;font-size:13px}.header-actions{display:flex;gap:10px;flex-wrap:wrap}.header-actions .ant-select{width:210px}.summary-row{display:flex;align-items:center;gap:26px;background:#fff;padding:14px 20px;border:1px solid #e4eaf3;border-radius:10px;margin-bottom:16px;font-size:12px;color:#74849b}.summary-row b{font-size:21px;color:#3156b1;margin-right:6px}.summary-row>small{margin-left:auto;color:#94a0b3}.design-workspace{display:grid;grid-template-columns:230px minmax(0,1fr) 355px;gap:12px;align-items:stretch;height:calc(100dvh - 260px);min-height:590px}.outline-panel,.map-panel,.detail-panel{background:white;border:1px solid #e4eaf3;border-radius:12px;min-width:0;min-height:0}.outline-panel{display:flex;flex-direction:column;padding:16px 12px}.panel-title{font-weight:600;display:flex;justify-content:space-between;margin-bottom:16px}.panel-title small{font-weight:400;color:#93a0b3}.outline-actions{display:flex;gap:12px;padding:12px 0}.outline-actions button,.map-breadcrumb button{border:0;background:transparent;color:#71849d;font-size:12px;cursor:pointer;padding:0}.outline-scroll{flex:1;overflow:auto}.outline-scroll :deep(.ant-tree-title){font-size:12px;overflow-wrap:anywhere}.outline-scroll :deep(.ant-tree-indent-unit){width:14px}.outline-scroll :deep(.ant-tree-node-content-wrapper){min-width:0}.node-count{color:#94a3b8;margin-left:8px;font-size:10px}.search-hit{color:#225de0;background:#e9f1ff}.outline-note{font-size:11px;line-height:1.7;border-top:1px solid #eef2f7;padding-top:14px;color:#8a98ad;margin-top:12px}.map-panel{display:flex;flex-direction:column;overflow:hidden;background:#fafcff}.map-heading{display:flex;justify-content:space-between;align-items:center;padding:16px;gap:8px;background:white;border-bottom:1px solid #eef2f7;font-size:13px}.map-heading>div{display:flex;gap:6px;flex-wrap:wrap}.map-breadcrumb{display:flex;flex-wrap:wrap;gap:8px;padding:10px 16px;font-size:12px}.map-breadcrumb span{margin-left:6px;color:#b8c3d3}.map-panel :deep(.mind-canvas){flex:1;min-height:0;padding:30px 24px;background-image:radial-gradient(#e3e9f3 1px,transparent 1px);background-size:20px 20px}.map-panel :deep(.mm-node){border-radius:8px;box-shadow:none;max-width:270px;white-space:normal;text-align:left;flex-shrink:0}.map-panel :deep(.mm-node .label){min-width:70px;line-height:1.6;overflow-wrap:anywhere}.map-panel :deep(.mm-node.root){background:#345cd1;border-color:#345cd1;color:white;box-shadow:none}.map-panel :deep(.mm-kids.horizontal){margin-left:36px;gap:14px}.map-legend{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 16px;font-size:10px;color:#7c8ca2;background:white;border-top:1px solid #eef2f7}.map-legend small{flex-basis:100%;color:#9aa7b8}.legend-dot{height:8px;width:8px;border-radius:50%;display:inline-block}.legend-dot.blue{background:#7097e7}.legend-dot.green{background:#6ac4a7}.legend-dot.purple{background:#b49ae7}.detail-panel{padding:20px;overflow:auto}.detail-type{font-size:10px;letter-spacing:1px;color:#6b8bd1}.detail-panel h3{font-size:20px;line-height:1.5;margin:8px 0}.detail-path{color:#95a0b2;font-size:11px;line-height:1.6;overflow-wrap:anywhere}.detail-stats{display:flex;gap:16px;font-size:12px;color:#6c7e97;border-bottom:1px solid #eef2f7;padding-bottom:16px}.section-title{display:flex;align-items:center;justify-content:space-between;margin:20px 0 10px;font-size:13px}.section-title small{color:#9aa6b8}.section-hint,.empty-coverage p{font-size:11px;line-height:1.7;color:#8997ab}.candidate-row{display:flex;align-items:center;gap:10px;border:1px solid #e5ebf4;border-radius:8px;padding:10px;margin-bottom:8px}.candidate-row.current{border-color:#8caaf3;background:#f3f7ff}.candidate-row>button{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0;border:0;background:transparent;text-align:left;cursor:pointer}.candidate-row b{font-size:12px;line-height:1.6;font-weight:500}.candidate-row small{color:#8c9bb1;font-size:10px}.child-section>button{display:flex;justify-content:space-between;gap:12px;width:100%;border:0;border-bottom:1px solid #f0f3f8;background:white;padding:12px 0;text-align:left;cursor:pointer;font-size:12px}.child-section small{white-space:nowrap;color:#8e9db3}.evidence-card{padding:16px 0;border-bottom:1px solid #edf1f7}.evidence-card small{font-size:10px;color:#9aa4b4}.evidence-title-button{display:block;font-size:13px;line-height:1.7;font-weight:600;text-align:left;border:0;background:transparent;cursor:pointer;padding:8px 0 0}.evidence-card p{font-size:12px;line-height:1.8;color:#718098;margin:8px 0;overflow-wrap:anywhere}.evidence-source{font-size:10px;color:#96a1b2;overflow-wrap:anywhere}.source-link{border:0;background:transparent;color:#4273c8;font-size:11px;padding:8px 0 0;cursor:pointer}.evidence-pagination{margin-top:16px}.load-error{margin-bottom:16px}.initial-loading{padding:80px;text-align:center;color:#8a98ad}.compare-notice{color:#76869f;line-height:1.8;font-size:13px}.comparison-scroll{overflow:auto}.comparison-table{width:100%;border-collapse:collapse;table-layout:fixed;min-width:650px}.comparison-table th,.comparison-table td{padding:14px;border:1px solid #e5eaf3;vertical-align:top;font-size:12px;line-height:1.8}.comparison-table th{background:#f6f8fc;text-align:left}.comparison-table th:first-child{width:105px}.comparison-table th small{display:block;color:#8b9bb1;font-weight:400;margin-top:6px}.compare-excerpt{display:block;width:100%;border:0;border-bottom:1px solid #edf1f7;background:white;text-align:left;padding:0 0 12px;margin-bottom:12px;cursor:pointer;overflow-wrap:anywhere}.compare-excerpt p{color:#6e7e95;line-height:1.8;font-size:12px}.compare-excerpt small{color:#8b9cb6;font-size:10px}.no-evidence{color:#a4adbb}.source-modal{display:flex;gap:20px;align-items:flex-start}.source-text{flex:1;min-width:0;max-height:72vh;overflow:auto}.source-modal :deep(.pdf-viewer){flex:1;min-width:0}.source-heading{padding-bottom:12px;border-bottom:1px solid #eef2f7}.source-heading p{font-size:12px;color:#8b9cb1}.source-content{line-height:1.9;font-size:14px;overflow-wrap:anywhere}.source-content :deep(img){max-width:100%}.source-content :deep(pre){overflow:auto}.source-content :deep(table){display:block;overflow:auto;max-width:100%}.source-content :deep(.katex-display){overflow:auto}.empty-coverage{margin-top:30px}
@media(max-width:1400px){.design-workspace{grid-template-columns:200px minmax(0,1fr) 310px}.detail-panel{padding:16px}.map-heading{align-items:flex-start;flex-direction:column}}
@media(max-width:1150px){.design-workspace{grid-template-columns:200px minmax(0,1fr);height:auto}.map-panel{height:620px}.outline-panel{max-height:620px}.detail-panel{grid-column:1/-1;max-height:650px}.summary-row{gap:16px;flex-wrap:wrap}.summary-row>small{margin-left:0}.design-header{align-items:flex-start;flex-direction:column}.source-modal{flex-direction:column}.source-modal :deep(.pdf-viewer){width:100%}}
@media(max-width:700px){.design-workspace{grid-template-columns:1fr}.outline-panel{max-height:320px}.map-panel{height:460px}.header-actions{width:100%}.header-actions .ant-select{width:100%}.detail-panel{max-height:none}.summary-row{gap:12px}.summary-row b{font-size:18px}.map-heading{flex-direction:row;flex-wrap:wrap}}
</style>
