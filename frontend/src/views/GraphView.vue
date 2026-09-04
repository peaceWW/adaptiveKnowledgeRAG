<template>
  <div class="graph-page">
    <div class="hero">
      <h2>知识图谱</h2>
      <p>探索概念、约束与解决方案之间的关联</p>
    </div>

    <div class="workspace">
      <aside class="side-pane">
        <div class="pane-title">筛选</div>
        <a-form layout="vertical">
          <a-form-item label="节点类型">
            <a-select v-model:value="nodeType" @change="load">
              <a-select-option value="all">全部</a-select-option>
              <a-select-option value="concept">概念</a-select-option>
              <a-select-option value="unit">知识单元</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="关系类型">
            <a-select v-model:value="relationType" @change="load">
              <a-select-option value="all">全部</a-select-option>
              <a-select-option v-for="item in relationTypes" :key="item" :value="item">{{ item }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="搜索节点">
            <a-input-search v-model:value="keyword" placeholder="搜索节点..." allow-clear @search="load" />
          </a-form-item>
        </a-form>
        <div class="pane-title">显示选项</div>
        <a-checkbox v-model:checked="showLabels">显示标签</a-checkbox>
        <a-checkbox v-model:checked="showRelations">显示关系</a-checkbox>
        <a-checkbox v-model:checked="showWeights">显示权重</a-checkbox>
      </aside>

      <section class="canvas-pane" ref="canvasBox" @wheel.prevent="onWheel">
        <div class="toolbar">
          <button type="button" title="重新布局" @click="relayout">⌘</button>
          <button type="button" title="适应画布" @click="fitView">⤢</button>
          <button type="button" title="放大" @click="zoomBy(1.15)">＋</button>
          <button type="button" title="缩小" @click="zoomBy(0.85)">－</button>
        </div>
        <svg
          class="canvas"
          :viewBox="`0 0 ${size.w} ${size.h}`"
          @mousedown="onDown"
          @mousemove="onMove"
          @mouseup="onUp"
          @mouseleave="onUp"
        >
          <g :transform="`translate(${pan.x} ${pan.y}) scale(${zoom})`">
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="#94a3b8" />
              </marker>
            </defs>
            <line
              v-for="edge in layout.edges"
              :key="edge.id"
              :x1="edge.x1"
              :y1="edge.y1"
              :x2="edge.x2"
              :y2="edge.y2"
              class="edge"
              marker-end="url(#arrow)"
            />
            <text
              v-if="showRelations"
              v-for="edge in layout.edges"
              :key="edge.id + '-label'"
              :x="(edge.x1 + edge.x2) / 2"
              :y="(edge.y1 + edge.y2) / 2 - 6"
              class="edge-label"
            >
              {{ edge.type }}{{ showWeights && edge.weight ? ` ${edge.weight}` : "" }}
            </text>
            <g v-for="node in layout.nodes" :key="node.id" class="node" @click.stop="select(node)">
              <circle v-if="node.hub" :cx="node.x" :cy="node.y" r="36" class="hub" :class="{ selected: selectedId === node.id }" />
              <rect
                v-else
                :x="node.x - 58"
                :y="node.y - 18"
                width="116"
                height="36"
                rx="8"
                class="leaf"
                :class="[nodeTone(node), { selected: selectedId === node.id }]"
              />
              <text v-if="showLabels" :x="node.x" :y="node.y + 4" text-anchor="middle" class="node-label" :class="{ light: node.hub }">
                {{ node.label }}
              </text>
            </g>
          </g>
        </svg>
        <a-empty v-if="!nodes.length" class="empty" description="没有匹配的图谱节点" />
      </section>

      <aside class="side-pane detail-pane">
        <div class="pane-title">节点信息</div>
        <template v-if="selected">
          <div class="field"><span>节点名称</span><b>{{ selected.label }}</b></div>
          <div class="field"><span>节点类型</span><a-tag>{{ typeLabel(selected.type) }}</a-tag></div>
          <div class="field"><span>描述</span><p>{{ selected.description || "暂无描述" }}</p></div>
          <div class="field"><span>连接关系</span><b>{{ degree(selected.id) }}</b></div>
          <div class="field"><span>知识单元</span><b>{{ selected.unit_count || 0 }}</b></div>
          <div class="pane-title">关联文档（{{ (selected.documents || []).length }}）</div>
          <a-empty v-if="!(selected.documents || []).length" description="暂无关联文档" />
          <button
            v-for="doc in selected.documents || []"
            :key="doc.id"
            type="button"
            class="doc-item"
            @click="openDoc(doc)"
          >
            📄 {{ doc.filename }}
          </button>
          <a-button type="primary" block class="detail-btn" @click="viewDetail">查看详情</a-button>
        </template>
        <a-empty v-else description="点击节点查看详情" />
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api";

const router = useRouter();
const keyword = ref("CDC");
const nodeType = ref("all");
const relationType = ref("all");
const showLabels = ref(true);
const showRelations = ref(true);
const showWeights = ref(true);
const nodes = ref<any[]>([]);
const edges = ref<any[]>([]);
const relationTypes = ref<string[]>([]);
const selectedId = ref<string>();
const hubId = ref<string>("");
const zoom = ref(1);
const pan = reactive({ x: 0, y: 0 });
const size = { w: 900, h: 640 };
const dragging = ref(false);
const last = reactive({ x: 0, y: 0 });
const canvasBox = ref<HTMLElement | null>(null);

const selected = computed(() => nodes.value.find((item) => item.id === selectedId.value));
const layout = computed(() => {
  const list = nodes.value;
  const hub = list.find((item) => item.id === hubId.value) || list[0];
  const others = list.filter((item) => item !== hub);
  const cx = size.w / 2;
  const cy = size.h / 2;
  const placed: any[] = [];
  if (hub) placed.push({ ...hub, x: cx, y: cy, hub: true });
  others.forEach((node, index) => {
    const angle = (index / Math.max(others.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const radius = 210 + (index % 2) * 28;
    placed.push({
      ...node,
      hub: false,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });
  const map = new Map(placed.map((item) => [item.id, item]));
  const drawn = edges.value.map((edge, index) => {
    const from = map.get(edge.source);
    const to = map.get(edge.target);
    if (!from || !to) return null;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.max(Math.hypot(dx, dy), 1);
    const trim = from.hub ? 40 : 28;
    return {
      id: `${edge.source}-${edge.target}-${index}`,
      type: edge.type,
      weight: edge.weight,
      x1: from.x + (dx / dist) * trim,
      y1: from.y + (dy / dist) * trim,
      x2: to.x - (dx / dist) * (to.hub ? 40 : 58),
      y2: to.y - (dy / dist) * (to.hub ? 40 : 20),
    };
  }).filter(Boolean);
  return { nodes: placed, edges: drawn as any[] };
});

function typeLabel(type = "concept") {
  return { concept: "概念", unit: "知识单元", document: "文档" }[type] || type;
}
function nodeTone(node: any) {
  const rel = edges.value.find((item) => item.target === node.id)?.type || "";
  if (rel.includes("PROBLEM")) return "problem";
  if (rel.includes("SOLUTION") || rel.includes("EXAMPLE")) return "solution";
  if (rel.includes("CONSTRAINT") || rel.includes("EXCEPTION")) return "constraint";
  if (node.role === "root_cause" || node.role === "principle") return "problem";
  if (node.role === "solution" || node.role === "example") return "solution";
  if (node.role === "constraint") return "constraint";
  return "plain";
}
function degree(id: string) {
  return edges.value.filter((item) => item.source === id || item.target === id).length;
}

async function load() {
  const { data } = await api.get("/graph", {
    params: {
      name: keyword.value,
      node_type: nodeType.value === "all" ? "" : nodeType.value,
      relation_type: relationType.value === "all" ? "" : relationType.value,
    },
  });
  nodes.value = data.nodes || [];
  edges.value = data.edges || [];
  relationTypes.value = data.filters?.relation_types || [];
  hubId.value = data.hub || nodes.value[0]?.id;
  selectedId.value = hubId.value;
  fitView();
}

function select(node: any) {
  selectedId.value = node.id;
}
function relayout() {
  nodes.value = [...nodes.value];
}
function fitView() {
  zoom.value = 1;
  pan.x = 0;
  pan.y = 0;
}
function zoomBy(factor: number) {
  zoom.value = Math.min(2.4, Math.max(0.4, zoom.value * factor));
}
function onWheel(event: WheelEvent) {
  zoomBy(event.deltaY > 0 ? 0.92 : 1.08);
}
function onDown(event: MouseEvent) {
  dragging.value = true;
  last.x = event.clientX;
  last.y = event.clientY;
}
function onMove(event: MouseEvent) {
  if (!dragging.value) return;
  pan.x += event.clientX - last.x;
  pan.y += event.clientY - last.y;
  last.x = event.clientX;
  last.y = event.clientY;
}
function onUp() {
  dragging.value = false;
}
function openDoc(doc: any) {
  router.push({ name: "review", query: { documentId: doc.id } });
}
function viewDetail() {
  const node = selected.value;
  if (!node) return;
  if (node.unit_id) {
    router.push({ name: "unit-detail", params: { id: node.unit_id } });
    return;
  }
  if (node.documents?.[0]?.id) {
    router.push({ name: "review", query: { documentId: node.documents[0].id } });
    return;
  }
  if (node.unit_ids?.[0]) {
    router.push({ name: "unit-detail", params: { id: node.unit_ids[0] } });
  }
}

onMounted(load);
</script>

<style scoped>
.graph-page { max-width: 1440px; }
.hero h2 { margin: 0; }
.hero p { margin: 6px 0 12px; color: #6b7280; }
.workspace {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr) 300px;
  gap: 12px;
  min-height: calc(100vh - 170px);
}
.side-pane, .canvas-pane {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.side-pane { padding: 16px; overflow: auto; }
.pane-title { font-weight: 700; margin: 8px 0 10px; }
.side-pane :deep(.ant-checkbox-wrapper) { display: flex; margin: 8px 0; }
.canvas-pane { position: relative; overflow: hidden; background: #f8fafc; }
.canvas { width: 100%; height: 100%; min-height: 560px; cursor: grab; }
.toolbar {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  gap: 6px;
  z-index: 2;
}
.toolbar button {
  width: 32px;
  height: 32px;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 8px;
  cursor: pointer;
}
.edge { stroke: #94a3b8; stroke-width: 1.6; }
.edge-label { font-size: 10px; fill: #64748b; text-anchor: middle; }
.hub { fill: #2563eb; stroke: #1d4ed8; }
.node-label { font-size: 11px; fill: #111827; pointer-events: none; }
.node-label.light { fill: #fff; font-weight: 700; }
.leaf { stroke-width: 1.5; }
.leaf.problem { fill: #dcfce7; stroke: #86efac; }
.leaf.solution { fill: #fee2e2; stroke: #fca5a5; }
.leaf.constraint { fill: #ffedd5; stroke: #fdba74; }
.leaf.plain { fill: #eff6ff; stroke: #93c5fd; }
.selected { stroke: #2563eb !important; stroke-width: 3 !important; }
.field { margin-bottom: 10px; }
.field span { display: block; color: #6b7280; font-size: 12px; }
.field p { margin: 4px 0 0; color: #374151; }
.doc-item {
  width: 100%;
  text-align: left;
  border: 0;
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
}
.detail-btn { margin-top: 12px; }
.empty { position: absolute; inset: 0; display: grid; place-items: center; }
@media (max-width: 1100px) {
  .workspace { grid-template-columns: 1fr; }
}
</style>
