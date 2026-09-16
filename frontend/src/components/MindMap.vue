<template>
  <div class="mind-canvas" :class="direction" ref="canvas">
    <svg class="mind-links" :width="size.w" :height="size.h">
      <path v-for="line in lines" :key="line.id" :d="line.d" fill="none" stroke="#cbd5e1" stroke-width="2" />
    </svg>
    <div class="mind-tree" :class="direction">
      <MindBranch
        :node="root"
        :selected-id="selectedId"
        :collapsed="collapsed"
        :matches="matches"
        :direction="direction"
        @select="(id: string) => $emit('select', id)"
        @toggle="(id: string) => $emit('toggle', id)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import MindBranch from "./MindBranch.vue";

const props = defineProps<{
  root: any;
  selectedId?: string;
  collapsed: Record<string, boolean>;
  matches: Set<string>;
  direction: "horizontal" | "vertical";
}>();

defineEmits<{
  select: [id: string];
  toggle: [id: string];
}>();

const canvas = ref<HTMLElement | null>(null);
const size = reactive({ w: 800, h: 600 });
const lines = ref<{ id: string; d: string }[]>([]);
let observer: ResizeObserver | undefined;

function collectPairs(node: any, pairs: { from: string; to: string }[] = []) {
  if (!node || props.collapsed[node.id]) return pairs;
  for (const child of node.children || []) {
    pairs.push({ from: node.id, to: child.id });
    collectPairs(child, pairs);
  }
  return pairs;
}

function draw() {
  const el = canvas.value;
  if (!el || !props.root) return;
  size.w = Math.max(el.scrollWidth, el.clientWidth);
  size.h = Math.max(el.scrollHeight, el.clientHeight);
  const box = el.getBoundingClientRect();
  const next: { id: string; d: string }[] = [];
  for (const pair of collectPairs(props.root)) {
    const from = el.querySelector(`[data-id="${pair.from}"]`) as HTMLElement | null;
    const to = el.querySelector(`[data-id="${pair.to}"]`) as HTMLElement | null;
    if (!from || !to) continue;
    const a = from.getBoundingClientRect();
    const b = to.getBoundingClientRect();
    const x1 = a.left + (props.direction === "horizontal" ? a.width : a.width / 2) - box.left + el.scrollLeft;
    const y1 = a.top + (props.direction === "horizontal" ? a.height / 2 : a.height) - box.top + el.scrollTop;
    const x2 = b.left + (props.direction === "horizontal" ? 0 : b.width / 2) - box.left + el.scrollLeft;
    const y2 = b.top + (props.direction === "horizontal" ? b.height / 2 : 0) - box.top + el.scrollTop;
    const dx = (x2 - x1) / 2;
    const dy = (y2 - y1) / 2;
    const d =
      props.direction === "horizontal"
        ? `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
        : `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
    next.push({ id: `${pair.from}-${pair.to}`, d });
  }
  lines.value = next;
}

watch(
  () => [props.root, props.collapsed, props.selectedId, props.direction, props.matches],
  async () => {
    await nextTick();
    requestAnimationFrame(draw);
  },
  { deep: true },
);

onMounted(() => {
  draw();
  observer = new ResizeObserver(() => draw());
  if (canvas.value) observer.observe(canvas.value);
  window.addEventListener("resize", draw);
});
onBeforeUnmount(() => {
  observer?.disconnect();
  window.removeEventListener("resize", draw);
});

function focusNode(id: string) {
  const el = canvas.value;
  const node = el?.querySelector(`[data-id="${CSS.escape(id)}"]`) as HTMLElement | null;
  if (!el || !node) return;
  const box = el.getBoundingClientRect();
  const target = node.getBoundingClientRect();
  el.scrollTo({
    left: Math.max(0, el.scrollLeft + target.left - box.left - 24),
    top: Math.max(0, el.scrollTop + target.top - box.top + target.height / 2 - el.clientHeight / 2),
  });
}

defineExpose({ draw, focusNode });
</script>

<style scoped>
.mind-canvas {
  position: relative;
  min-height: 520px;
  overflow: auto;
  padding: 28px 20px;
}
.mind-links {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: visible;
}
.mind-tree.horizontal { display: flex; align-items: center; min-width: max-content; }
.mind-tree.vertical { display: flex; flex-direction: column; align-items: center; min-height: max-content; }
</style>
