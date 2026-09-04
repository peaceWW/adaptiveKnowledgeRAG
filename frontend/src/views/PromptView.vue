<template>
  <div>
    <div class="page-title">Prompt / Skill Center</div>
    <a-row :gutter="16">
      <a-col :span="8">
        <a-card v-for="p in prompts" :key="p.id" style="margin-bottom: 8px" @click="current = { ...p }">
          <b>{{ p.prompt_id }}</b>
          <p>Version {{ p.version }} · {{ p.status }} · {{ p.model }}</p>
          <p>Success Rate：{{ p.success_rate }}</p>
        </a-card>
      </a-col>
      <a-col :span="16">
        <a-card v-if="current" title="Prompt Editor">
          <a-row :gutter="12">
            <a-col :span="12">
              <a-textarea v-model:value="current.content" :rows="18" />
              <a-button type="primary" style="margin-top: 8px" @click="save">保存</a-button>
            </a-col>
            <a-col :span="12">
              <a-textarea v-model:value="inputText" :rows="8" placeholder="测试输入" />
              <a-button style="margin: 8px 0" @click="run">Run Test</a-button>
              <pre>{{ JSON.stringify(output, null, 2) }}</pre>
            </a-col>
          </a-row>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";

const prompts = ref<any[]>([]);
const current = ref<any>(null);
const inputText = ref("如何解决 CDC？");
const output = ref<any>({});

async function load() {
  prompts.value = (await api.get("/prompts")).data;
  current.value = prompts.value[0];
}

async function save() {
  await api.put(`/prompts/${current.value.id}`, { content: current.value.content });
  await load();
}

async function run() {
  output.value = (await api.post(`/prompts/${current.value.id}/test`, {
    content: current.value.content,
    input_text: inputText.value,
  })).data.output;
}

onMounted(load);
</script>
