<template>
  <a-card v-if="unit" :title="unit.title">
    <p>Type：{{ unit.knowledge_type }} · Role：{{ unit.semantic_role }} · {{ unit.lifecycle }} · {{ unit.version }}</p>
    <p>{{ unit.content }}</p>
    <p>Source：{{ unit.source_chapter }} p.{{ unit.source_page }}</p>
  </a-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const unit = ref<any>(null);

onMounted(async () => {
  unit.value = (await api.get(`/knowledge-units/${route.params.id}`)).data;
});
</script>
