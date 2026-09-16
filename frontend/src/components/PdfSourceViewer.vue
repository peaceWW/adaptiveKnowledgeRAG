<template>
  <div class="pdf-viewer" :class="{ expanded }">
    <div class="pdf-toolbar">
      <div class="page-controls">
        <a-button :disabled="!manifest || page <= 1" aria-label="上一页 PDF" @click="setPage(page - 1)">‹</a-button>
        <span>第</span>
        <a-input-number :value="page" :min="1" :max="manifest?.page_count || 1" :precision="0" :controls="false" :disabled="!manifest" aria-label="PDF 页码" class="page-input" @change="setPage" />
        <span>/ {{ manifest?.page_count || '—' }} 页</span>
        <a-button :disabled="!manifest || page >= manifest.page_count" aria-label="下一页 PDF" @click="setPage(page + 1)">›</a-button>
      </div>
      <div class="view-controls">
        <a-select v-model:value="zoom" :options="zoomOptions" aria-label="PDF 缩放" class="zoom-select" />
        <a-button v-if="mode !== 'document'" :disabled="!manifest || !validSourcePage" @click="locateSource">定位知识点</a-button>
        <a-button @click="expanded = !expanded">{{ expanded ? '退出大图' : '大图阅读' }}</a-button>
        <a-button :loading="downloading" :disabled="!manifest" @click="download">下载原 PDF</a-button>
      </div>
    </div>
    <div class="source-location">
      <span>{{ locationLabel }}</span>
      <span>原始 PDF 页面 · 保留排版、图片与公式</span>
    </div>
    <div ref="viewport" class="pdf-viewport" :aria-busy="loading">
      <div v-if="error" class="viewer-state">
        <a-alert type="warning" show-icon message="暂时无法展示原 PDF" :description="error" />
        <a-space wrap>
          <a-button type="primary" @click="retry">重新加载</a-button>
          <a-button v-if="mode !== 'document'" @click="$emit('showText')">查看提取文本</a-button>
        </a-space>
      </div>
      <div v-else-if="loading" class="viewer-state"><a-spin size="large" /><p>正在加载 PDF 原始页面…</p></div>
      <div v-else-if="imageUrl" class="paper" :style="{ width: `${zoom}%`, maxWidth: expanded ? `${1600 * zoom / 100}px` : undefined }">
        <img :src="imageUrl" :alt="`${filename}，原 PDF 第 ${page} 页`" draggable="false" @error="error = '页面图像加载失败，请重试'" />
      </div>
    </div>
    <div class="pdf-footer">{{ filename }}<span v-if="manifest"> · {{ manifest.page_count }} 页</span></div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import axios from 'axios';
import { api } from '../api';

const props = withDefaults(defineProps<{ documentId: string; filename: string; sourcePage?: number; sourceKey: string; mode?: 'evidence' | 'document' }>(), { mode: 'evidence' });
defineEmits<{ showText: [] }>();
const manifest = ref<{ page_count: number } | null>(null);
const page = ref(1);
const zoom = ref(100);
const zoomOptions = [{ value: 100, label: '适合宽度' }, { value: 125, label: '放大 125%' }, { value: 150, label: '放大 150%' }, { value: 200, label: '放大 200%' }];
const expanded = ref(false);
const loading = ref(true);
const downloading = ref(false);
const error = ref('');
const imageUrl = ref('');
const viewport = ref<HTMLElement>();
const validSourcePage = computed(() => Number.isInteger(props.sourcePage) && Number(props.sourcePage) >= 1 && Number(props.sourcePage) <= (manifest.value?.page_count || 0));
const locationLabel = computed(() => {
  if (props.mode === 'document') return manifest.value ? `文档原文 · 共 ${manifest.value.page_count} 页` : '文档原文';
  return validSourcePage.value ? `知识点来源：第 ${props.sourcePage} 页` : '此知识点未记录有效来源页，请手动翻页核对';
});
const cache = new Map<string, string>();
let controller: AbortController | undefined;
let version = 0;
let disposed = false;

function setPage(value: number | string | null) {
  if (!manifest.value || value === null) return;
  const target = Number(value);
  if (Number.isFinite(target)) page.value = Math.max(1, Math.min(Math.round(target), manifest.value.page_count));
}
function locateSource() {
  if (validSourcePage.value) setPage(props.sourcePage!);
  viewport.value?.scrollTo({ top: 0, left: 0 });
}
async function errorText(err: unknown) {
  if (axios.isAxiosError(err)) {
    let data = err.response?.data;
    if (data instanceof Blob) {
      try { data = JSON.parse(await data.text()); } catch { data = null; }
    }
    if (typeof data?.detail === 'string') return data.detail;
  }
  return '原始文件无法读取。请检查服务连接，或确认上传时保存的 PDF 仍然存在。';
}
async function loadPage() {
  if (!manifest.value || disposed) return;
  const request = ++version;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = '';
  imageUrl.value = '';
  const width = expanded.value || zoom.value > 100 ? 3000 : 2000;
  const key = `${page.value}:${width}`;
  try {
    let url = cache.get(key);
    if (!url) {
      const { data } = await api.get(`/documents/${props.documentId}/pages/${page.value}`, {
        params: { width }, responseType: 'blob', signal: controller.signal,
      });
      if (request !== version || disposed) return;
      url = URL.createObjectURL(data);
      cache.set(key, url);
      if (cache.size > 6) {
        const oldest = cache.keys().next().value!;
        URL.revokeObjectURL(cache.get(oldest)!);
        cache.delete(oldest);
      }
    }
    imageUrl.value = url;
    viewport.value?.scrollTo({ top: 0, left: 0 });
  } catch (err) {
    if (!axios.isCancel(err)) {
      const description = await errorText(err);
      if (request === version && !disposed) error.value = description;
    }
  } finally {
    if (request === version && !disposed) loading.value = false;
  }
}
async function initialize() {
  const request = ++version;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = '';
  try {
    const { data } = await api.get(`/documents/${props.documentId}/source`, { signal: controller.signal });
    if (request !== version || disposed) return;
    if (!Number.isInteger(data.page_count) || data.page_count < 1) throw new Error('Invalid page count');
    manifest.value = data;
    const target = validSourcePage.value ? props.sourcePage! : 1;
    if (page.value !== target) page.value = target;
    else await loadPage();
  } catch (err) {
    if (!axios.isCancel(err) && request === version && !disposed) {
      error.value = await errorText(err);
      loading.value = false;
    }
  }
}
function retry() { return manifest.value ? loadPage() : initialize(); }
async function download() {
  downloading.value = true;
  try {
    const { data } = await api.get(`/documents/${props.documentId}/original`, { responseType: 'blob' });
    const url = URL.createObjectURL(data);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = props.filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } finally { downloading.value = false; }
}
function onKey(event: KeyboardEvent) { if (event.key === 'Escape') expanded.value = false; }
watch([page, zoom, expanded], loadPage);
watch(() => props.sourceKey, () => {
  if (manifest.value) setPage(validSourcePage.value ? props.sourcePage! : 1);
  viewport.value?.scrollTo({ top: 0, left: 0 });
});
onMounted(() => { initialize(); document.addEventListener('keydown', onKey); });
onBeforeUnmount(() => {
  disposed = true;
  version++;
  controller?.abort();
  cache.forEach(url => URL.revokeObjectURL(url));
  document.removeEventListener('keydown', onKey);
});
</script>

<style scoped>
.pdf-viewer { display: flex; flex-direction: column; flex: 1; min-height: 0; min-width: 0; overflow: hidden; border: 1px solid #dbe2ec; border-radius: 8px; background: #f1f4f8; }
.pdf-toolbar { padding: 10px 12px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; background: #fff; border-bottom: 1px solid #e2e8f0; }
.page-controls, .view-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.page-input { width: 54px; }
.zoom-select { width: 116px; }
.source-location { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; padding: 8px 12px; color: #64748b; font-size: 12px; }
.pdf-viewport { flex: 1; min-height: 0; overflow: auto; padding: 20px; background: #e7ecf2; }
.paper { margin: 0 auto; background: white; box-shadow: 0 3px 14px #0f172a24; line-height: 0; }
.paper img { display: block; width: 100%; height: auto; max-width: none; }
.viewer-state { padding: 48px 12px; text-align: center; color: #64748b; }
.viewer-state .ant-space { margin-top: 16px; }
.pdf-footer { padding: 8px 12px; font-size: 12px; color: #64748b; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.expanded { position: fixed; inset: 16px; z-index: 1100; box-shadow: 0 0 0 20px #0f172a80; }
@media (max-width: 700px) {
  .pdf-viewport { padding: 10px; }
  .pdf-toolbar { padding: 8px; }
  .source-location span:last-child { display: none; }
  .expanded { inset: 4px; }
}
</style>
