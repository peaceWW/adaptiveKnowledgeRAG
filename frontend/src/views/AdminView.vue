<template>
  <div>
    <div class="page-title">系统管理</div>
    <a-card title="服务健康" style="margin-bottom: 16px">
      <a-tag v-for="(v, k) in health" :key="k" :color="v === true || v === false ? (v ? 'green' : 'red') : 'blue'">
        {{ k }}：{{ v }}
      </a-tag>
    </a-card>
    <a-card title="用户与角色">
      <a-table :columns="userCols" :data-source="users" row-key="id" />
    </a-card>
    <a-card title="ACL" style="margin-top: 16px">
      <a-table :columns="aclCols" :data-source="acl" row-key="id" />
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";

const health = ref<Record<string, unknown>>({});
const users = ref<any[]>([]);
const acl = ref<any[]>([]);
const userCols = [
  { title: "用户", dataIndex: "username" },
  { title: "角色", dataIndex: "role" },
  { title: "部门", dataIndex: "department" },
];
const aclCols = [
  { title: "KB", dataIndex: "kb_id" },
  { title: "主体", dataIndex: "principal_id" },
  { title: "权限", dataIndex: "permission" },
];

onMounted(async () => {
  health.value = (await api.get("/admin/health")).data;
  users.value = (await api.get("/admin/users")).data;
  acl.value = (await api.get("/admin/acl")).data;
});
</script>
