<template>
  <div class="strategy-page">
    <div class="hero">
      <div>
        <h2>Knowledge Strategy Builder</h2>
        <a-select v-model:value="currentId" class="strategy-select" @change="pick">
          <a-select-option v-for="item in strategies" :key="item.id" :value="item.id">{{ item.name }}</a-select-option>
        </a-select>
      </div>
      <a-button type="primary" @click="openCreate">+ 添加策略</a-button>
    </div>

    <div v-if="form" class="workspace">
      <section class="config-pane">
        <a-form layout="vertical">
          <a-form-item label="Strategy Name">
            <a-input v-model:value="form.name" />
          </a-form-item>
          <a-form-item label="Chunk Policy">
            <a-radio-group v-model:value="form.chunk_policy">
              <a-radio-button value="semantic_unit">Semantic Unit</a-radio-button>
              <a-radio-button value="section">Section</a-radio-button>
              <a-radio-button value="fixed_token">Fixed Token</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item>
            <template #label>
              <div class="role-head">
                <span>Define Knowledge Roles</span>
                <a-button type="link" size="small" @click="showRole = true">+ 添加 Role</a-button>
              </div>
            </template>
            <div class="role-grid">
              <div v-for="group in roleGroups" :key="group.name" class="role-col">
                <div class="role-col-title">{{ group.name }}</div>
                <a-checkbox
                  v-for="role in group.roles"
                  :key="role.key"
                  :checked="(form.roles || []).includes(role.key)"
                  @change="(e: any) => toggleRole(role.key, e.target.checked)"
                >
                  {{ role.label }}
                </a-checkbox>
                <a-button type="link" size="small" @click="selectGroup(group)">Select All</a-button>
              </div>
            </div>
          </a-form-item>
          <a-form-item label="Completeness Threshold">
            <div class="threshold">
              <a-slider
                :min="0"
                :max="1"
                :step="0.01"
                :value="coverage"
                @change="(v: number) => (form.completeness_policy.minimum_coverage = v)"
              />
              <b>{{ coverage.toFixed(2) }}</b>
            </div>
            <div class="hint">Threshold for accepted chunk relevance</div>
          </a-form-item>
          <a-button type="primary" :loading="saving" @click="save">Save Strategy</a-button>
        </a-form>
      </section>

      <section class="preview-pane">
        <div class="card">
          <div class="card-title">Strategy Preview</div>
          <p class="preview-text">
            <span
              v-for="(part, index) in previewParts"
              :key="index"
              :style="part.color ? { background: part.color, borderRadius: '3px', padding: '0 2px' } : {}"
              :title="part.role"
            >{{ part.text }}</span>
          </p>
          <div class="legend">
            <span v-for="item in preview.legend || []" :key="item.role">
              <i :style="{ background: item.color }" /> {{ item.label }}
            </span>
          </div>
        </div>
        <div class="side">
          <div class="card">
            <div class="card-title">Predicted Distribution</div>
            <div v-for="item in preview.distribution || []" :key="item.role" class="bar-row">
              <span>{{ item.label }}</span>
              <a-progress :percent="item.percent" size="small" :show-info="false" :stroke-color="item.color" />
              <em>{{ item.percent }}%</em>
            </div>
            <a-empty v-if="!(preview.distribution || []).length" description="选择 Role 后预览分布" />
          </div>
          <div class="card">
            <div class="card-title">Strategy Performance</div>
            <div class="metrics">
              <div>
                <span>Mean Precision</span>
                <b>{{ preview.metrics?.precision ?? "--" }}</b>
              </div>
              <div>
                <span>Recall Rate</span>
                <b>{{ preview.metrics?.recall ?? "--" }}</b>
              </div>
              <div>
                <span>F1 Score</span>
                <b>{{ preview.metrics?.f1 ?? "--" }}</b>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <a-modal v-model:open="showCreate" title="添加新策略" @ok="createStrategy">
      <a-form layout="vertical">
        <a-form-item label="名称"><a-input v-model:value="createForm.name" /></a-form-item>
        <a-form-item label="文档类型">
          <a-select v-model:value="createForm.knowledge_type">
            <a-select-option value="technical_concept">技术概念 / 规范</a-select-option>
            <a-select-option value="incident_case">故障案例</a-select-option>
            <a-select-option value="api_document">API 文档</a-select-option>
            <a-select-option value="enterprise_process">企业流程</a-select-option>
            <a-select-option value="legal_rule">法规条款</a-select-option>
            <a-select-option value="historical_event">历史事件</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="复制自当前策略">
          <a-switch v-model:checked="createForm.clone" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="showRole" title="添加 Knowledge Role" @ok="createRole">
      <a-form layout="vertical">
        <a-form-item label="显示名称"><a-input v-model:value="roleForm.label" placeholder="例如 policy" /></a-form-item>
        <a-form-item label="Key"><a-input v-model:value="roleForm.key" placeholder="可选，默认由名称生成" /></a-form-item>
        <a-form-item label="分类">
          <a-select v-model:value="roleForm.category" show-search>
            <a-select-option v-for="name in categoryNames" :key="name" :value="name">{{ name }}</a-select-option>
            <a-select-option value="CUSTOM">CUSTOM</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="匹配关键词（逗号分隔）">
          <a-input v-model:value="roleForm.keywords" placeholder="政策, policy, 规定" />
        </a-form-item>
        <a-form-item label="高亮颜色"><a-input v-model:value="roleForm.color" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { message } from "ant-design-vue";
import { api } from "../api";

const strategies = ref<any[]>([]);
const roleCatalog = ref<any[]>([]);
const currentId = ref<string>();
const form = ref<any>(null);
const preview = ref<any>({ legend: [], distribution: [], metrics: {}, text: "", spans: [] });
const saving = ref(false);
const showCreate = ref(false);
const showRole = ref(false);
const createForm = reactive({ name: "", knowledge_type: "technical_concept", clone: true });
const roleForm = reactive({ label: "", key: "", category: "CORE CONCEPTS", keywords: "", color: "#93c5fd" });
let previewTimer: number | undefined;

const coverage = computed(() => Number(form.value?.completeness_policy?.minimum_coverage ?? 0.9));
const categoryNames = computed(() => [...new Set(roleCatalog.value.map((item) => item.category))]);
const roleGroups = computed(() => {
  const groups: Record<string, any[]> = {};
  for (const role of roleCatalog.value) {
    groups[role.category] = groups[role.category] || [];
    groups[role.category].push(role);
  }
  return Object.entries(groups).map(([name, roles]) => ({ name, roles }));
});
const previewParts = computed(() => {
  const text = preview.value.text || "";
  const spans = preview.value.spans || [];
  const parts: { text: string; color?: string; role?: string }[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start > cursor) parts.push({ text: text.slice(cursor, span.start) });
    parts.push({ text: span.text, color: span.color, role: span.label });
    cursor = span.end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
});

async function load() {
  const [s, r] = await Promise.all([api.get("/strategies"), api.get("/strategies/roles")]);
  strategies.value = s.data;
  roleCatalog.value = r.data;
  currentId.value = currentId.value || strategies.value[0]?.id;
  pick();
}

function pick() {
  const found = strategies.value.find((item) => item.id === currentId.value);
  form.value = found ? JSON.parse(JSON.stringify(found)) : null;
  if (form.value) {
    form.value.roles = Array.isArray(form.value.roles) ? form.value.roles : [];
    form.value.completeness_policy = form.value.completeness_policy || { minimum_coverage: 0.9 };
  }
  schedulePreview();
}

function toggleRole(key: string, checked: boolean) {
  const roles = form.value.roles || [];
  form.value.roles = checked ? [...new Set([...roles, key])] : roles.filter((item: string) => item !== key);
}

function selectGroup(group: { roles: any[] }) {
  const keys = group.roles.map((item) => item.key);
  form.value.roles = [...new Set([...(form.value.roles || []), ...keys])];
}

async function refreshPreview() {
  if (!form.value) return;
  const { data } = await api.post("/strategies/preview", { roles: form.value.roles || [] });
  preview.value = data;
}

function schedulePreview() {
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(refreshPreview, 250);
}

async function save() {
  saving.value = true;
  try {
    await api.put(`/strategies/${form.value.id}`, {
      name: form.value.name,
      roles: form.value.roles,
      chunk_policy: form.value.chunk_policy,
      completeness_policy: form.value.completeness_policy,
    });
    message.success("已保存，后续抽取与召回将使用新 roles / coverage");
    const id = form.value.id;
    await load();
    currentId.value = id;
    pick();
  } finally {
    saving.value = false;
  }
}

function openCreate() {
  createForm.name = "";
  createForm.knowledge_type = form.value?.knowledge_type || "technical_concept";
  createForm.clone = true;
  showCreate.value = true;
}

async function createStrategy() {
  if (!createForm.name.trim()) {
    message.warning("请填写策略名称");
    return;
  }
  const { data } = await api.post("/strategies", {
    name: createForm.name.trim(),
    knowledge_type: createForm.knowledge_type,
    clone_id: createForm.clone ? currentId.value : undefined,
  });
  showCreate.value = false;
  message.success("已创建策略");
  await load();
  currentId.value = data.id;
  pick();
}

async function createRole() {
  if (!roleForm.label.trim()) {
    message.warning("请填写 Role 名称");
    return;
  }
  const { data } = await api.post("/strategies/roles", {
    label: roleForm.label.trim(),
    key: roleForm.key,
    category: roleForm.category,
    color: roleForm.color,
    keywords: roleForm.keywords.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
  });
  showRole.value = false;
  roleForm.label = "";
  roleForm.key = "";
  roleForm.keywords = "";
  message.success("已添加 Knowledge Role");
  await load();
  if (form.value && !form.value.roles.includes(data.key)) form.value.roles.push(data.key);
}

watch(
  () => [form.value?.roles, form.value?.completeness_policy?.minimum_coverage],
  schedulePreview,
  { deep: true },
);

onMounted(load);
</script>

<style scoped>
.strategy-page { max-width: 1280px; }
.hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
.hero h2 { margin: 0 0 8px; }
.strategy-select { width: 280px; }
.workspace { display: grid; grid-template-columns: minmax(360px, 0.95fr) minmax(0, 1.15fr); gap: 14px; }
.config-pane, .card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  padding: 16px;
}
.role-head { display: flex; justify-content: space-between; align-items: center; }
.role-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.role-col { background: #f8fafc; border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 4px; }
.role-col-title { font-size: 11px; font-weight: 700; color: #6b7280; margin-bottom: 4px; }
.threshold { display: grid; grid-template-columns: 1fr 48px; gap: 8px; align-items: center; }
.hint { color: #9ca3af; font-size: 12px; }
.preview-pane { display: grid; grid-template-columns: minmax(0, 1.2fr) 220px; gap: 12px; }
.card-title { font-weight: 700; margin-bottom: 10px; }
.preview-text { white-space: pre-wrap; line-height: 1.8; color: #374151; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; color: #6b7280; font-size: 12px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }
.bar-row { display: grid; grid-template-columns: 86px 1fr 40px; gap: 6px; align-items: center; font-size: 12px; margin: 6px 0; }
.bar-row em { font-style: normal; color: #6b7280; text-align: right; }
.metrics { display: grid; gap: 10px; }
.metrics span { color: #6b7280; font-size: 12px; }
.metrics b { display: block; font-size: 22px; }
.side { display: flex; flex-direction: column; gap: 12px; }
@media (max-width: 1100px) {
  .workspace, .preview-pane { grid-template-columns: 1fr; }
}
</style>
