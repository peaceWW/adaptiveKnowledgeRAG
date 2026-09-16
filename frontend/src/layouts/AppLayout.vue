<template>
  <a-layout style="min-height: 100vh">
    <a-layout-header class="header">
      <div class="brand">Adaptive Knowledge RAG</div>
      <a-input-search
        v-model:value="keyword"
        class="search"
        placeholder="搜索知识库名称、领域、描述…"
        allow-clear
        @search="onSearch"
      />
      <a-space :size="16" class="account">
        <span class="header-icon" title="最近问答" @click="$router.push({ name: 'chat' })">🕒</span>
        <a-select :value="session.username" style="width: 200px" @change="onUser">
          <a-select-option value="alice">Alice · 普通用户</a-select-option>
          <a-select-option value="bob">Bob · 知识专家</a-select-option>
          <a-select-option value="carol">Carol · 算法工程师</a-select-option>
          <a-select-option value="admin">Admin · 系统管理员</a-select-option>
        </a-select>
      </a-space>
    </a-layout-header>
    <a-layout>
      <a-layout-sider theme="light" :width="220" breakpoint="lg" :collapsed-width="0" class="sidebar">
        <a-menu
          :selected-keys="[String(route.name)]"
          :open-keys="openKeys"
          mode="inline"
          @click="onMenu"
          @openChange="(keys: string[]) => (openKeys = keys)"
        >
          <a-menu-item v-if="can('dashboard')" key="dashboard">工作台</a-menu-item>
          <a-menu-item v-if="can('chat')" key="chat">智能问答</a-menu-item>
          <a-sub-menu v-if="can('kb')" key="kb-group" title="知识库">
            <a-menu-item key="kb">知识库</a-menu-item>
            <a-menu-item v-if="can('documents')" key="documents">文档管理</a-menu-item>
            <a-menu-item v-if="can('review')" key="review">知识审核</a-menu-item>
            <a-menu-item v-if="can('catalog')" key="catalog">知识目录</a-menu-item>
          </a-sub-menu>
          <a-menu-item v-if="can('strategies')" key="strategies">策略中心</a-menu-item>
          <a-menu-item v-if="can('retrieval')" key="retrieval">检索中心</a-menu-item>
          <a-menu-item v-if="can('graph')" key="graph">知识图谱</a-menu-item>
          <a-menu-item v-if="can('evaluation')" key="evaluation">评估中心</a-menu-item>
          <a-menu-item v-if="can('prompts')" key="prompts">模型中心</a-menu-item>
          <a-menu-item v-if="can('admin')" key="admin">系统管理</a-menu-item>
        </a-menu>
      </a-layout-sider>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { useSession, type UserRole } from "../stores/session";

const route = useRoute();
const router = useRouter();
const session = useSession();
const keyword = ref("");
const openKeys = ref(["kb-group"]);

const roleMap: Record<string, UserRole> = {
  alice: "end_user",
  bob: "knowledge_expert",
  carol: "algorithm_engineer",
  admin: "admin",
};

function can(key: string) {
  return session.allowed.includes(key);
}

function onMenu(info: { key: string }) {
  if (info.key === "kb-group") return;
  router.push({ name: info.key });
}

function onUser(username: string) {
  session.setUser(username, roleMap[username]);
}

function onSearch(value: string) {
  const q = value.trim();
  if (!q) return;
  message.info(`正在知识库中查找「${q}」`);
  router.push({ name: "kb", query: { q } });
}
</script>

<style scoped>
.header {
  background: #fff;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 24px;
  border-bottom: 1px solid #eef2f7;
  height: 64px;
  line-height: 64px;
}
.brand {
  font-weight: 700;
  color: #1d4ed8;
  white-space: nowrap;
}
.search {
  flex: 1;
  max-width: 520px;
}
.header-icon {
  cursor: pointer;
  font-size: 16px;
}
.content {
  min-width: 0;
  margin: 0;
  padding: 20px 24px 32px;
  background: #f4f6fb;
  min-height: calc(100vh - 64px);
}
.account { margin-left: auto; }
.content :deep(> div) { width: 100%; max-width: none; }
.sidebar { border-right: 1px solid #e6ebf2; }
@media (max-width: 760px) {
  .header { height: auto; min-height: 64px; flex-wrap: wrap; gap: 12px; padding: 12px 16px; line-height: normal; }
  .search { order: 3; flex-basis: 100%; max-width: none; }
  .content { padding: 20px 16px; }
}
</style>
