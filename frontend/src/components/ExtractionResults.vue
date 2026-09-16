<template>
  <div class="extraction-results">
    <a-alert v-if="enabled === false" type="info" show-icon message="本次抽取未启用此类内容" description="以文档抽取时的策略配置为准；修改策略不会自动改变已有结果。" />
    <a-empty v-if="!items.length && enabled !== false" :description="emptyText" />
    <article v-for="item in pagedItems" :key="item.id" class="result-card" :class="{ selected: item.id === selectedId }">
      <header><div><strong>{{ item.title }}</strong><div class="result-meta">{{ item.source_page ? `来源：第 ${item.source_page} 页` : '未记录来源页' }} · {{ roleLabels[item.semantic_role] || item.semantic_role }} · 置信度 {{ Math.round(item.confidence * 100) }}%</div></div><a-tag v-if="item.unit_meta?.stub" color="orange">待补充识别</a-tag></header>
      <DocumentAsset v-if="['equation', 'figure'].includes(kind) || item.unit_meta?.image_key || item.unit_meta?.image_url" :document-id="documentId" :image-key="item.unit_meta?.image_key" :image-url="item.unit_meta?.image_url" :alt="item.title" />
      <template v-if="kind === 'equation'">
        <div v-if="item.unit_meta?.latex"><div class="field-label">公式表达式（LaTeX）</div><pre class="formula-source">{{ item.unit_meta.latex }}</pre></div>
        <div v-else-if="item.unit_meta?.source_expression"><div class="field-label">原始公式文本</div><pre class="formula-source">{{ item.unit_meta.source_expression }}</pre></div>
        <p v-if="item.unit_meta?.meaning">{{ item.unit_meta.meaning }}</p>
        <dl v-if="Object.keys(item.unit_meta?.variables || {}).length" class="variables"><template v-for="(meaning, symbol) in item.unit_meta.variables" :key="symbol"><dt>{{ symbol }}</dt><dd>{{ meaning }}</dd></template></dl>
        <p v-if="item.unit_meta?.recognition_status === 'unavailable'" class="hint">视觉识别未完成，请结合原稿核对公式与符号。</p>
      </template>
      <template v-if="kind === 'figure'">
        <p v-if="item.unit_meta?.caption"><b>图注：</b>{{ item.unit_meta.caption }}</p>
        <p v-if="item.unit_meta?.description"><b>图像解读：</b>{{ item.unit_meta.description }}</p>
        <p v-if="item.unit_meta?.asset_status === 'linked_only'" class="hint">原文仅包含图片链接，图片文件未随文档上传。</p>
        <p v-if="item.unit_meta?.recognition_status === 'unavailable'" class="hint">视觉解读未完成，当前保留原图及图注。</p>
      </template>
      <div v-if="kind === 'table' && item.unit_meta?.rows?.length" class="table-scroll"><table><tbody><tr v-for="(row, index) in item.unit_meta.rows" :key="index"><td v-for="(cell, column) in row" :key="column" :class="{ 'table-heading': index === 0 }">{{ cell }}</td></tr></tbody></table></div>
      <div v-else-if="kind === 'table'" class="hint">仅识别到表格位置或标题，尚无结构化单元格，请对照原稿。</div>
      <p v-if="kind === 'table' && item.unit_meta?.recognition_status === 'unavailable'" class="hint">表格视觉核对未完成，当前保留单元格与截图。</p>
      <div v-if="kind === 'text' || kind === 'citation'" class="result-content">{{ item.content }}</div>
      <details v-else class="extracted-details"><summary>查看完整提取内容</summary><pre>{{ item.content }}</pre></details>
      <div v-if="item.unit_meta?.custom_roles?.length" class="custom-tags"><a-tag v-for="role in item.unit_meta.custom_roles" :key="role">{{ customLabels[role] || role }}</a-tag></div>
      <footer><a-button size="small" :type="item.id === selectedId ? 'primary' : 'default'" @click="$emit('select', item.id)">{{ item.id === selectedId ? '当前审核知识点' : '审核此知识点' }}</a-button><a-button size="small" @click="$emit('locate', item.id)">定位原稿</a-button></footer>
    </article>
    <a-pagination v-if="items.length > 8" v-model:current="page" :total="items.length" :page-size="8" :show-size-changer="false" />
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import DocumentAsset from './DocumentAsset.vue';
import { extractionKind, roleLabels } from '../knowledge';
const props = defineProps<{ documentId: string; units: any[]; kind: string; selectedId?: string; enabled?: boolean | null; customLabels: Record<string, string> }>();
defineEmits<{ select: [id: string]; locate: [id: string] }>();
const page = ref(1);
const items = computed(() => props.units.filter(item => extractionKind(item) === props.kind));
const pagedItems = computed(() => items.value.slice((page.value - 1) * 8, page.value * 8));
const emptyText = computed(() => ({ text: '暂无文本知识单元', equation: '暂无公式提取结果；原文可能没有可识别公式，或历史抽取尚未生成此类内容', figure: '暂无图片提取结果；请在原稿中核对图片是否被识别', table: '暂无表格提取结果', citation: '暂无参考文献条目' }[props.kind] || '暂无提取结果'));
watch(() => [props.kind, props.documentId], () => { page.value = 1; });
watch(() => props.selectedId, id => { const index = items.value.findIndex(item => item.id === id); if (index >= 0) page.value = Math.floor(index / 8) + 1; });
</script>
<style scoped>
.extraction-results { min-height: 0; flex: 1; overflow: auto; padding: 4px; }
.result-card { border: 1px solid #e2e8f0; padding: 18px; border-radius: 10px; margin-bottom: 16px; overflow-wrap: anywhere; }
.result-card.selected { border-color: #60a5fa; box-shadow: inset 3px 0 #3b82f6; }
header { display: flex; justify-content: space-between; gap: 12px; } .result-meta, .hint { color: #64748b; font-size: 12px; line-height: 1.7; margin-top: 6px; }
.field-label { color: #475569; font-size: 12px; margin: 12px 0 6px; } .formula-source { padding: 14px; background: #f1f5f9; white-space: pre-wrap; overflow-wrap: anywhere; }
.variables { display: grid; grid-template-columns: minmax(60px, auto) 1fr; gap: 8px 16px; } dt { font-weight: 600; } dd { margin: 0; }
.result-content, .extracted-details pre { white-space: pre-wrap; line-height: 1.8; margin-top: 16px; overflow-wrap: anywhere; }
.extracted-details { margin-top: 16px; } summary { cursor: pointer; color: #2563eb; }
.table-scroll { overflow: auto; margin: 16px 0; } table { border-collapse: collapse; width: 100%; } td { border: 1px solid #dbe2ec; padding: 8px 12px; min-width: 70px; } .table-heading { background: #eff6ff; font-weight: 600; }
footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 16px; } .custom-tags { margin-top: 12px; }
</style>
