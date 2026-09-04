<template>
  <div class="mm-wrap" :class="direction">
    <button
      type="button"
      class="mm-node"
      :class="[node.tone, { root: node.isRoot, selected: selectedId === node.id, hit: matches.has(node.id), leaf: node.isLeaf }]"
      :data-id="node.id"
      @click.stop="$emit('select', node.id)"
    >
      <span class="icon">{{ node.icon || "📘" }}</span>
      <span class="label">{{ node.name }}</span>
      <span v-if="!node.isLeaf && node.children?.length" class="badge" @click.stop="$emit('toggle', node.id)">
        {{ collapsed[node.id] ? "+" : "–" }}
      </span>
    </button>
    <div v-if="!collapsed[node.id] && node.children?.length" class="mm-kids" :class="direction">
      <MindBranch
        v-for="child in node.children"
        :key="child.id"
        :node="child"
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
defineOptions({ name: "MindBranch" });

defineProps<{
  node: any;
  selectedId?: string;
  collapsed: Record<string, boolean>;
  matches: Set<string>;
  direction: "horizontal" | "vertical";
}>();

defineEmits<{
  select: [id: string];
  toggle: [id: string];
}>();
</script>

<style scoped>
.mm-wrap { display: flex; align-items: center; }
.mm-wrap.vertical { flex-direction: column; }
.mm-kids.horizontal {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  margin-left: 48px;
}
.mm-kids.vertical {
  display: flex;
  flex-direction: row;
  justify-content: center;
  gap: 16px;
  margin-top: 36px;
}
.mm-node {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 12px;
  padding: 8px 12px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  white-space: nowrap;
  color: #111827;
}
.mm-node.root {
  background: #fff7ed;
  border-color: #fdba74;
  box-shadow: 0 0 0 4px rgba(251, 146, 60, 0.25);
  font-weight: 700;
}
.mm-node.blue { background: #eff6ff; border-color: #93c5fd; }
.mm-node.green { background: #ecfdf5; border-color: #6ee7b7; }
.mm-node.purple { background: #f5f3ff; border-color: #c4b5fd; }
.mm-node.cyan { background: #ecfeff; border-color: #67e8f9; }
.mm-node.leaf { background: #fff; }
.mm-node.selected { outline: 2px solid #2563eb; }
.mm-node.hit { box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25); }
.icon { font-size: 14px; }
.label { font-size: 13px; }
.badge {
  min-width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #111827;
  color: #fff;
  font-size: 12px;
  display: grid;
  place-items: center;
  margin-left: 4px;
}
</style>
