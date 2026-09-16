<template>
  <div class="prompt-page">
    <div class="page-title">模型中心</div>
    <p class="page-lead">
      全部提示词默认站在「芯片设计工程师设计芯片」的视角：抽取要可核对，检索要系统，回答不得编造工艺与指标。
      此处保存后立即用于分类、抽取、图解读与智能问答。
    </p>
    <a-row :gutter="16">
      <a-col :span="8">
        <a-card
          v-for="p in prompts"
          :key="p.id"
          class="prompt-card"
          :class="{ active: current?.id === p.id }"
          @click="current = { ...p }"
        >
          <b>{{ p.title || p.prompt_id }}</b>
          <p class="muted">{{ p.prompt_id }} · {{ p.version }} · {{ stageLabel(p.strategy) }}</p>
        </a-card>
      </a-col>
      <a-col :span="16">
        <a-card v-if="current" :title="current.title || current.prompt_id">
          <a-row :gutter="12">
            <a-col :span="12">
              <a-textarea v-model:value="current.content" :rows="18" />
              <a-button type="primary" style="margin-top: 8px" @click="save">保存并立即生效</a-button>
            </a-col>
            <a-col :span="12">
              <a-textarea v-model:value="inputText" :rows="8" placeholder="用芯片设计问题或一段电路原文做测试" />
              <a-button style="margin: 8px 0" @click="run">试运行</a-button>
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
const inputText = ref("嵌入式 FFE 如何降低 SAR ADC 的量化噪声？给出约束与指标条件。");
const output = ref<any>({});

const stages: Record<string, string> = {
  all: "入库 · 分类",
  configured_snapshot: "入库 · 抽取",
  technical_concept: "入库 · 论文/图",
  document_index: "入库 · 检索标注",
  retrieval: "问答 · 理解/规划/生成",
};

function stageLabel(strategy: string) {
  return stages[strategy] || strategy || "未分组";
}

async function load() {
  prompts.value = (await api.get("/prompts")).data;
  current.value = prompts.value.find((item: any) => item.id === current.value?.id) || prompts.value[0];
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

<style scoped>
.page-lead { color: #64748b; margin: -8px 0 16px; max-width: 920px; }
.prompt-card { margin-bottom: 8px; cursor: pointer; }
.prompt-card.active { outline: 1px solid #1677ff; }
.muted { color: #64748b; margin: 6px 0 0; font-size: 12px; }
pre { background: #f8fafc; padding: 8px; min-height: 180px; overflow: auto; }
</style>
