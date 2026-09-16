<template>
  <div class="asset-frame">
    <a-spin v-if="loading" />
    <a-image v-else-if="url && !error" :src="url" :preview="preview" :alt="alt" :style="{ maxWidth: '100%' }" @error="error = '图片加载失败，请查看引用来源。'" />
    <a-alert v-else type="info" :message="error || '未保存对应截图，请定位到 PDF 原稿核对。'" show-icon />
    <div v-if="showUrl && publicUrl" class="asset-url">图片地址：{{ publicUrl }}</div>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import axios from 'axios';
import { api } from '../api';
const props = withDefaults(defineProps<{ documentId: string; imageKey?: string; imageUrl?: string; alt: string; preview?: boolean; showUrl?: boolean }>(), { showUrl: true, preview: true });
const preview = computed(() => props.preview !== false);
const url = ref(''), loading = ref(false), error = ref('');
let controller: AbortController | undefined, version = 0;
const publicUrl = computed(() => {
  if (props.imageUrl) return props.imageUrl;
  if (props.documentId && props.imageKey) {
    return `/api/documents/${props.documentId}/assets?key=${encodeURIComponent(props.imageKey)}`;
  }
  return '';
});
function revokeBlob() {
  if (url.value.startsWith('blob:')) URL.revokeObjectURL(url.value);
}
watch(() => [props.documentId, props.imageKey, props.imageUrl], async () => {
  const request = ++version;
  controller?.abort(); controller = new AbortController();
  revokeBlob();
  url.value = ''; error.value = ''; loading.value = false;
  if (props.imageUrl) { url.value = props.imageUrl; return; }
  if (!props.imageKey) return;
  loading.value = true;
  try {
    const { data } = await api.get(`/documents/${props.documentId}/assets`, { params: { key: props.imageKey }, responseType: 'blob', signal: controller.signal });
    if (request === version) url.value = URL.createObjectURL(data);
  } catch (err) { if (!axios.isCancel(err) && request === version) error.value = '截图读取失败，请在原稿中核对。'; }
  finally { if (request === version) loading.value = false; }
}, { immediate: true });
onBeforeUnmount(() => { version++; controller?.abort(); revokeBlob(); });
</script>
<style scoped>
.asset-frame { background: #f8fafc; border: 1px solid #e2e8f0; padding: 14px; border-radius: 8px; text-align: center; margin: 12px 0; }
.asset-frame :deep(img) { max-width: 100%; max-height: 480px; object-fit: contain; }
.asset-url { margin-top: 8px; font-size: 12px; color: #64748b; word-break: break-all; text-align: left; }
</style>
