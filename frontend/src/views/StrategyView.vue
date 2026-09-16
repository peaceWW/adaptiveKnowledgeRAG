<template>
  <div class="strategy-page">
    <div class="hero">
      <div><h2>策略中心</h2><p>配置上传文档的提取内容、文本拆分方式与知识类别</p></div>
      <a-space wrap><a-select v-model:value="currentId" class="strategy-select" :disabled="saving" @change="pick">
        <a-select-option v-for="item in strategies" :key="item.id" :value="item.id">{{ strategyLabel(item.name) }}</a-select-option>
      </a-select><a-button @click="openCreate">添加策略</a-button><a-button type="primary" :loading="saving" :disabled="!form" @click="save">保存策略</a-button></a-space>
    </div>
    <a-alert type="info" show-icon message="保存后的策略用于后续文档抽取。已有知识单元保留原来的结果和审核状态。" class="notice" />
    <a-spin :spinning="loading">
      <div v-if="form" class="workspace">
        <section class="config-pane">
          <a-form layout="vertical">
            <h3>基本信息</h3>
            <a-form-item label="策略名称"><a-input v-model:value="form.name" :maxlength="200" /></a-form-item>
            <h3>提取内容</h3>
            <div class="extraction-grid">
              <div v-for="item in extractionCategories" :key="item.key" class="extraction-option" :class="{ selected: form.extraction_policy[item.policy_key] }">
                <a-checkbox v-model:checked="form.extraction_policy[item.policy_key]">{{ item.label }}</a-checkbox>
                <span>{{ item.description }}</span>
              </div>
            </div>
            <div class="mode-grid">
              <a-form-item v-if="form.extraction_policy.formulas" label="公式处理方式"><a-select v-model:value="form.extraction_policy.formula_mode" :options="formulaModes" /></a-form-item>
              <a-form-item v-if="form.extraction_policy.images" label="图片处理方式"><a-select v-model:value="form.extraction_policy.image_mode" :options="imageModes" /></a-form-item>
              <a-form-item v-if="form.extraction_policy.tables" label="表格处理方式"><a-select v-model:value="form.extraction_policy.table_mode" :options="tableModes" /></a-form-item>
            </div>
            <p class="hint">视觉识别需要已配置的视觉模型；不可用时保留原稿截图与来源，并标明识别未完成。文档中仅有图片链接时不会自动下载外部图片。</p>
            <template v-if="form.extraction_policy.text">
              <h3>文本拆分</h3>
              <a-form-item label="拆分方式"><a-radio-group v-model:value="form.chunk_policy">
                <a-radio-button v-for="(label, key) in chunkLabels" :key="key" :value="key">{{ label }}</a-radio-button>
              </a-radio-group></a-form-item>
              <p class="hint">{{ chunkDescription }}</p>
              <div class="mode-grid">
                <a-form-item label="单段最大长度（字符）"><a-input-number v-model:value="form.extraction_policy.chunk_size" :min="200" :max="12000" :step="100" /></a-form-item>
                <a-form-item v-if="form.chunk_policy === 'fixed_token'" label="相邻段落重叠长度（字符）"><a-input-number v-model:value="form.extraction_policy.chunk_overlap" :min="0" :max="Math.min(2000, (form.extraction_policy.chunk_size || 200) - 1)" /></a-form-item>
              </div>
              <div class="role-head"><h3>文本知识类别</h3><a-button type="link" @click="showRole = true">添加自定义类别</a-button></div>
              <div class="role-grid"><div v-for="group in roleGroups" :key="group.name" class="role-col">
                <div class="role-col-title">{{ group.name }}<a-button type="link" size="small" @click="selectGroup(group)">全选</a-button></div>
                <a-checkbox v-for="role in group.roles" :key="role.key" :checked="form.roles.includes(role.key)" @change="(event: any) => toggleRole(role.key, event.target.checked)">{{ roleLabels[role.key] || role.label }}</a-checkbox>
              </div></div>
              <p class="hint">内置类别用于组织文本知识点；自定义类别按关键词为匹配内容添加标签。公式和参考文献由上方的独立提取开关控制。</p>
            </template>
            <a-form-item label="知识完整性阈值" class="coverage-control"><a-slider v-model:value="form.completeness_policy.minimum_coverage" :min="0" :max="1" :step="0.05" /><span>{{ Math.round(form.completeness_policy.minimum_coverage * 100) }}% · 仅检查本策略启用的内容，缺失项进入审核</span></a-form-item>
          </a-form>
        </section>
        <aside class="preview-pane">
          <section class="card"><h3>审核页将展示</h3><p class="hint">以下是配置说明，不是实际文档的提取结果。</p>
            <div v-for="item in extractionCategories" :key="item.key" class="result-row"><span>{{ item.label }}</span><a-tag :color="form.extraction_policy[item.policy_key] ? 'blue' : 'default'">{{ form.extraction_policy[item.policy_key] ? '已启用' : '已关闭' }}</a-tag></div>
            <div class="summary"><b>{{ chunkLabels[form.chunk_policy] }}</b><p v-if="form.extraction_policy.text">文本每段最多 {{ form.extraction_policy.chunk_size }} 字符；公式、图片、表格按上方开关独立成知识点，不会跟正文切在一起。</p><p v-else>本策略不生成文本知识单元，仅提取已启用的公式 / 图片 / 表格 / 参考文献。</p></div>
          </section>
          <section class="card"><h3>类别匹配示例</h3><p class="hint">使用示例文字按关键词标记类别，不代表模型精度或文档覆盖率。</p>
            <p class="preview-text"><span v-for="(part, index) in previewParts" :key="index" :style="part.color ? { background: part.color } : {}" :title="part.role">{{ part.text }}</span></p><a-empty v-if="!form.roles.length" description="尚未选择文本类别" />
          </section>
        </aside>
      </div>
      <a-empty v-else-if="!loading" description="还没有策略，请添加第一个策略" />
    </a-spin>
    <a-modal v-model:open="showCreate" title="添加策略" :confirm-loading="creating" @ok="createStrategy"><a-form layout="vertical">
      <a-form-item label="名称"><a-input v-model:value="createForm.name" :maxlength="200" /></a-form-item>
      <a-form-item label="知识类型"><a-select v-model:value="createForm.knowledge_type" :options="knowledgeTypes" /></a-form-item>
      <a-form-item label="复制当前策略的配置"><a-switch v-model:checked="createForm.clone" :disabled="!form" /></a-form-item>
    </a-form></a-modal>
    <a-modal v-model:open="showRole" title="添加自定义文本类别" :confirm-loading="creatingRole" @ok="createRole"><a-form layout="vertical">
      <a-form-item label="中文名称"><a-input v-model:value="roleForm.label" placeholder="例如：设计建议" /></a-form-item>
      <a-form-item label="类别标识（可选）"><a-input v-model:value="roleForm.key" placeholder="留空时根据名称生成" /></a-form-item>
      <a-form-item label="匹配关键词（逗号分隔）"><a-input v-model:value="roleForm.keywords" placeholder="建议，推荐，宜采用" /></a-form-item>
    </a-form></a-modal>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { message } from 'ant-design-vue';
import { api } from '../api';
import { chunkLabels, defaultExtractionPolicy, extractionCategories, roleLabels, strategyLabel } from '../knowledge';
const strategies = ref<any[]>([]), roleCatalog = ref<any[]>([]), currentId = ref<string>();
const form = ref<any>(null), preview = ref<any>({ text: '', spans: [] });
const saving = ref(false), loading = ref(true), creating = ref(false), creatingRole = ref(false), showCreate = ref(false), showRole = ref(false);
const createForm = reactive({ name: '', knowledge_type: 'technical_concept', clone: true });
const roleForm = reactive({ label: '', key: '', keywords: '' });
const formulaModes = [{ value: 'source', label: '保留原始公式与截图' }, { value: 'vision', label: '原稿截图 + 视觉识别公式与符号' }];
const imageModes = [{ value: 'source', label: '保留原图与图注' }, { value: 'vision', label: '原图图注 + 视觉理解' }];
const tableModes = [{ value: 'source', label: '保留表格单元格与截图' }, { value: 'vision', label: '表格截图 + 视觉核对（无模型时保留原稿）' }];
const knowledgeTypes = [{ value: 'technical_concept', label: '技术概念' }, { value: 'technical_specification', label: '技术规范' }, { value: 'incident_case', label: '故障案例' }, { value: 'api_document', label: '接口文档' }];
let timer: number | undefined;
let previewVersion = 0;
const roleGroups = computed(() => {
  const groups: Record<string, any[]> = {};
  for (const role of roleCatalog.value.filter(item => !['formula', 'reference'].includes(item.key))) (groups[role.category] ||= []).push(role);
  return Object.entries(groups).map(([name, roles]) => ({ name, roles }));
});
const chunkDescriptions: Record<string, string> = { semantic_unit: '按段落和语义组织知识点，长内容继续分段，保留章节上下文。', section: '按章节或标题边界拆分，超长章节继续分段，保留来源页。', fixed_token: '按字符数定长拆分，可设置重叠上下文；公式、图片和表格不会按字符打散。' };
const chunkDescription = computed(() => chunkDescriptions[form.value?.chunk_policy] || '');
const previewParts = computed(() => {
  const parts: { text: string; color?: string; role?: string }[] = [];
  let cursor = 0;
  for (const span of preview.value.spans || []) {
    if (span.start > cursor) parts.push({ text: preview.value.text.slice(cursor, span.start) });
    parts.push({ text: span.text, color: span.color, role: roleLabels[span.role] || span.label }); cursor = span.end;
  }
  if (cursor < (preview.value.text || '').length) parts.push({ text: preview.value.text.slice(cursor) });
  return parts;
});
async function load() {
  try { const [s, r] = await Promise.all([api.get('/strategies'), api.get('/strategies/roles')]); strategies.value = s.data; roleCatalog.value = r.data; currentId.value = currentId.value || strategies.value[0]?.id; pick(); }
  finally { loading.value = false; }
}
function pick() {
  const found = strategies.value.find(item => item.id === currentId.value);
  form.value = found ? JSON.parse(JSON.stringify(found)) : null;
  if (form.value) { form.value.name = strategyLabel(form.value.name); form.value.roles ||= []; form.value.extraction_policy = { ...defaultExtractionPolicy(), ...form.value.extraction_policy }; form.value.completeness_policy = { minimum_coverage: .9, ...form.value.completeness_policy }; }
}
function toggleRole(key: string, checked: boolean) { form.value.roles = checked ? [...new Set([...form.value.roles, key])] : form.value.roles.filter((item: string) => item !== key); }
function selectGroup(group: { roles: any[] }) { form.value.roles = [...new Set([...form.value.roles, ...group.roles.map(item => item.key)])]; }
async function save() {
  if (saving.value || !form.value) return;
  const policy = form.value.extraction_policy;
  if (!form.value.name.trim()) return message.warning('请填写策略名称');
  if (!extractionCategories.some(item => policy[item.policy_key])) return message.warning('请至少启用一种提取内容');
  if (policy.text && !form.value.roles.some((key: string) => !['formula', 'reference'].includes(key))) return message.warning('请选择至少一种文本知识类别');
  if (!policy.chunk_size || policy.chunk_overlap === null || policy.chunk_overlap >= policy.chunk_size) return message.warning('分段长度不能为空，重叠长度必须小于分段长度');
  saving.value = true;
  try { await api.put(`/strategies/${form.value.id}`, { name: form.value.name.trim(), roles: form.value.roles, chunk_policy: form.value.chunk_policy, extraction_policy: policy, completeness_policy: form.value.completeness_policy }); message.success('策略已保存，后续抽取将使用这些配置'); await load(); }
  finally { saving.value = false; }
}
function openCreate() { Object.assign(createForm, { name: '', knowledge_type: form.value?.knowledge_type || 'technical_concept', clone: !!form.value }); showCreate.value = true; }
async function createStrategy() {
  if (!createForm.name.trim()) return message.warning('请填写策略名称');
  if (creating.value) return;
  creating.value = true;
  try { const { data } = await api.post('/strategies', { name: createForm.name.trim(), knowledge_type: createForm.knowledge_type, clone_id: createForm.clone ? currentId.value : undefined }); currentId.value = data.id; showCreate.value = false; await load(); message.success('策略已创建'); }
  finally { creating.value = false; }
}
async function createRole() {
  const keywords = roleForm.keywords.split(/[,，]/).map(item => item.trim()).filter(Boolean);
  if (!roleForm.label.trim() || !keywords.length) return message.warning('请填写类别名称与匹配关键词');
  if (creatingRole.value) return;
  creatingRole.value = true;
  try { const { data } = await api.post('/strategies/roles', { label: roleForm.label.trim(), key: roleForm.key, category: 'CUSTOM', keywords, color: '#93c5fd' }); roleCatalog.value = (await api.get('/strategies/roles')).data; if (form.value) toggleRole(data.key, true); Object.assign(roleForm, { label: '', key: '', keywords: '' }); showRole.value = false; message.success('类别已添加，请保存策略以应用'); }
  finally { creatingRole.value = false; }
}
watch(() => form.value?.roles, () => {
  const version = ++previewVersion;
  if (timer) clearTimeout(timer);
  timer = window.setTimeout(async () => { if (!form.value) return; try { const { data } = await api.post('/strategies/preview', { roles: form.value.roles }); if (version === previewVersion) preview.value = data; } catch { /* API displays errors. */ } }, 250);
}, { deep: true });
onMounted(load);
onBeforeUnmount(() => { previewVersion++; if (timer) clearTimeout(timer); });
</script>
<style scoped>
.hero { display: flex; justify-content: space-between; gap: 20px; flex-wrap: wrap; margin-bottom: 18px; }
h2 { margin: 0; } h3 { margin: 0 0 16px; font-size: 16px; } .hero p { margin: 8px 0 0; color: #64748b; }
.strategy-select { width: 260px; } .notice { margin-bottom: 20px; }
.workspace { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 24px; align-items: start; }
.config-pane, .card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; }
.card + .card { margin-top: 20px; } .hint { font-size: 12px; color: #64748b; line-height: 1.7; margin: 0 0 18px; }
.extraction-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
.extraction-option { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; padding: 14px; border-radius: 8px; }
.extraction-option.selected { background: #f5f9ff; border-color: #93c5fd; } .extraction-option > span { color: #64748b; font-size: 12px; line-height: 1.6; }
.mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.role-head, .role-col-title { display: flex; justify-content: space-between; align-items: center; } .role-head h3 { margin-bottom: 0; } .role-head { margin: 0 0 16px; }
.role-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
.role-col { display: flex; flex-direction: column; gap: 8px; padding: 14px; border-radius: 8px; background: #f8fafc; } .role-col-title { color: #475569; font-weight: 600; } .coverage-control { margin: 24px 0 0; }
.result-row { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #f1f5f9; }
.summary { margin-top: 20px; background: #eff6ff; padding: 16px; border-radius: 8px; } .summary p { margin: 8px 0 0; color: #475569; }
.preview-text { white-space: pre-wrap; line-height: 2; } .preview-text span { border-radius: 3px; }
@media (max-width: 1100px) { .workspace { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .mode-grid, .extraction-grid { grid-template-columns: 1fr; } .config-pane, .card { padding: 16px; } .strategy-select { width: 210px; } }
</style>
