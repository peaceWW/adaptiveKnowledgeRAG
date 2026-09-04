<template>
  <div>
    <div class="page-title">知识库管理</div>
    <a-button type="primary" style="margin-bottom: 16px" @click="open = true">创建知识库</a-button>
    <a-row :gutter="16">
      <a-col v-for="kb in kbs" :key="kb.id" :span="12">
        <a-card :title="kb.name">
          <p>{{ kb.domain }} / {{ kb.strategy?.knowledge_type }}</p>
          <p>文档：{{ kb.document_count }}　Knowledge Unit：{{ kb.unit_count }}</p>
          <p>Strategy：{{ kb.strategy?.name }}</p>
          <a-tag color="green">{{ kb.status }}</a-tag>
        </a-card>
      </a-col>
    </a-row>
    <a-modal v-model:open="open" title="创建知识库" @ok="create">
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
import { onMounted, reactive, ref } from "vue";
import { api } from "../api";

const kbs = ref<any[]>([]);
const strategies = ref<any[]>([]);
const open = ref(false);
const form = reactive({
  name: "",
  description: "",
  domain: "semiconductor",
  strategy_id: undefined as string | undefined,
  access_scope: "public",
});

async function load() {
  kbs.value = (await api.get("/knowledge-bases")).data;
  strategies.value = (await api.get("/strategies")).data;
  form.strategy_id = strategies.value[0]?.id;
}

async function create() {
  await api.post("/knowledge-bases", form);
  open.value = false;
  await load();
}

onMounted(load);
</script>
