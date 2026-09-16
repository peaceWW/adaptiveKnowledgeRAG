<template>
  <div>
    <div class="page-title">知识库管理</div>
    <div class="kb-tools"><a-input-search v-model:value="keyword" allow-clear placeholder="搜索知识库名称、领域、描述" /><a-button type="primary" @click="open = true">创建知识库</a-button></div>
    <a-empty v-if="!filteredKbs.length && !loading" :description="kbs.length ? '没有匹配的知识库' : '创建第一个知识库，开始沉淀知识'" />
    <a-row :gutter="[20, 20]">
      <a-col v-for="kb in filteredKbs" :key="kb.id" :xs="24" :lg="12" :xxl="8">
        <a-card :title="kb.name">
          <p>{{ kb.domain }} / {{ kb.strategy?.knowledge_type }}</p>
          <p>{{ kb.description || '暂无描述' }}</p>
          <p>文档：{{ kb.document_count }}　知识点：{{ kb.unit_count }}</p>
          <p>抽取策略：{{ kb.strategy?.name || '未设置' }}</p>
          <a-tag color="green">{{ kb.status }}</a-tag>
          <a-button v-if="session.allowed.includes('documents')" type="link" @click="router.push({ name: 'documents', query: { kb_id: kb.id } })">管理文档 →</a-button>
        </a-card>
      </a-col>
    </a-row>
    <a-modal v-model:open="open" title="创建知识库" :confirm-loading="saving" @ok="create">
      <a-form layout="vertical">
        <a-form-item label="名称"><a-input v-model:value="form.name" /></a-form-item>
        <a-form-item label="描述"><a-textarea v-model:value="form.description" /></a-form-item>
        <a-form-item label="领域"><a-input v-model:value="form.domain" /></a-form-item>
        <a-form-item label="Strategy">
          <a-select v-model:value="form.strategy_id">
            <a-select-option v-for="s in strategies" :key="s.id" :value="s.id">{{ s.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="访问权限">
          <a-radio-group v-model:value="form.access_scope">
            <a-radio value="public">企业公开</a-radio>
            <a-radio value="department">指定部门</a-radio>
            <a-radio value="project">指定项目</a-radio>
          </a-radio-group>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from 'vue-router';
import { message } from 'ant-design-vue';
import { useSession } from '../stores/session';
import { api } from "../api";

const kbs = ref<any[]>([]);
const strategies = ref<any[]>([]);
const open = ref(false);
const route = useRoute();
const router = useRouter();
const session = useSession();
const keyword = ref(String(route.query.q || ''));
const saving = ref(false);
const loading = ref(true);
watch(() => route.query.q, value => { keyword.value = String(value || ''); });
const filteredKbs = computed(() => kbs.value.filter(kb => [kb.name, kb.domain, kb.description].join(' ').toLowerCase().includes(keyword.value.trim().toLowerCase())));
const form = reactive({
  name: "",
  description: "",
  domain: "semiconductor",
  strategy_id: undefined as string | undefined,
  access_scope: "public",
});

async function load() {
  try {
  kbs.value = (await api.get("/knowledge-bases")).data;
  strategies.value = (await api.get("/strategies")).data;
  form.strategy_id = strategies.value[0]?.id;
  } finally { loading.value = false; }
}

async function create() {
  if (!form.name.trim() || !form.domain.trim() || !form.strategy_id) { message.warning('请填写名称、领域并选择策略'); return; }
  if (saving.value) return;
  saving.value = true;
  try {
  await api.post("/knowledge-bases", { ...form, name: form.name.trim(), domain: form.domain.trim() });
  open.value = false;
  form.name = '';
  form.description = '';
  message.success('知识库已创建');
  await load();
  } finally { saving.value = false; }
}

onMounted(load);
</script>
<style scoped>
.kb-tools { display: flex; gap: 16px; justify-content: space-between; margin-bottom: 24px; }
.kb-tools .ant-input-search { max-width: 480px; }
</style>
