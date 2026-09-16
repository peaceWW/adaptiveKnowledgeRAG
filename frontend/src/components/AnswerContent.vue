<template>
  <div class="answer markdown-body">
    <template v-for="(part, index) in parts" :key="index">
      <div v-if="part.html" v-html="part.html"></div>
      <figure v-else-if="part.cite" class="answer-figure figure-grid">
        <DocumentAsset :document-id="part.cite.document_id || ''" :image-key="part.cite.image_key" :image-url="part.cite.image_key ? undefined : part.cite.image_url" :alt="part.cite.title || '知识库图片'" :show-url="false" />
        <figcaption>{{ part.cite.title }}<span v-if="part.cite.page"> · 第 {{ part.cite.page }} 页</span><button type="button" @click="$emit('source', part.cite)">查看来源 ↗</button></figcaption>
      </figure>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import { renderAnswer } from '../answer';
import DocumentAsset from './DocumentAsset.vue';
const props = defineProps<{ text: string; citations: any[]; pending?: boolean }>();
defineEmits<{ source: [citation: any] }>();
// Resolve only supplied evidence, so generated IDs cannot request arbitrary assets.
const parts = computed(() => {
  const figures = props.citations.filter(c => c.image_key || c.image_url);
  const used = new Set<any>();
  let text = props.text;
  // Older answers may contain image URLs, plain links, or storage keys.
  figures.forEach((cite, index) => {
    const marker = `[[figure:${cite.knowledge_id || `legacy-${index}`}]]`;
    for (const address of [cite.image_url, cite.image_key].filter(Boolean)) {
      const escaped = String(address).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      text = text.replace(new RegExp(`!?\\[[^\\]\\n]*\\]\\(<?${escaped}>?\\)`, 'g'), () => marker);
      text = text.split(address).join(marker);
    }
  });
  // Avoid flashing an incomplete control marker during streaming.
  if (props.pending) text = text.replace(/\[\[(?:f(?:i(?:g(?:u(?:r(?:e(?::[^\]]*)?)?)?)?)?)?)?\]?$/, '');
  const result: { html?: string; cite?: any }[] = [];
  const chunks = text.split(/(\[\[figure:[^\]\r\n]+\]\])/g);
  for (const chunk of chunks) {
    const id = /^\[\[figure:([^\]]+)\]\]$/.exec(chunk)?.[1];
    if (!id) { if (chunk.trim()) result.push({ html: renderAnswer(chunk) }); continue; }
    const cite = figures.find((c, i) => (c.knowledge_id || `legacy-${i}`) === id);
    if (cite && !used.has(cite)) { used.add(cite); result.push({ cite }); }
    else if (!cite) result.push({ html: '<p class="image-unavailable">图片暂不可用，请查看引用来源。</p>' });
  }
  // Historical answers without inline references still show their images.
  if (!props.pending) for (const cite of figures) if (!used.has(cite)) result.push({ cite });
  return result;
});
</script>
<style scoped>
.answer{font-size:15px;line-height:1.85;color:#263449;overflow-wrap:anywhere}
.answer :deep(h1),.answer :deep(h2),.answer :deep(h3){font-size:17px;color:#163d7c;margin:20px 0 10px}
.answer :deep(p){margin:0 0 12px}.answer :deep(table){display:block;max-width:100%;overflow:auto;border-collapse:collapse;margin:12px 0}.answer :deep(th),.answer :deep(td){border:1px solid #dde4ef;padding:6px 12px}.answer :deep(th){background:#edf3fc}
.answer :deep(pre){overflow:auto;background:#f5f7fb;padding:14px;border-radius:8px}.answer :deep(.katex-display){overflow-x:auto;overflow-y:hidden;background:#f6f9ff;border:1px solid #e1ebfc;border-radius:8px;padding:16px;margin:12px 0}.answer :deep(img){max-width:100%;max-height:480px;object-fit:contain}
.answer-figure{display:block;margin:14px 0;border:1px solid #dce8fa;border-radius:10px;overflow:hidden;background:white}.answer-figure :deep(.asset-frame){margin:0;border:0;background:white}.answer-figure figcaption{text-align:center;padding:8px 12px;color:#61718a;font-size:12px;background:#f8fbff}.answer-figure button{border:0;background:transparent;color:#2869cf;cursor:pointer;margin-left:12px}.image-unavailable{color:#8792a4}
</style>
