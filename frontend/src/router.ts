import { createRouter, createWebHistory } from "vue-router";
import AppLayout from "./layouts/AppLayout.vue";

const routes = [
  {
    path: "/",
    component: AppLayout,
    children: [
      { path: "", name: "dashboard", component: () => import("./views/DashboardView.vue") },
      { path: "chat", name: "chat", component: () => import("./views/ChatView.vue") },
      { path: "knowledge-bases", name: "kb", component: () => import("./views/KnowledgeBaseView.vue") },
      { path: "documents", name: "documents", component: () => import("./views/DocumentView.vue") },
      { path: "review", name: "review", component: () => import("./views/ReviewView.vue") },
      { path: "catalog", name: "catalog", component: () => import("./views/CatalogView.vue") },
      { path: "units/:id", name: "unit-detail", component: () => import("./views/UnitDetailView.vue") },
      { path: "strategies", name: "strategies", component: () => import("./views/StrategyView.vue") },
      { path: "prompts", name: "prompts", component: () => import("./views/PromptView.vue") },
      { path: "retrieval", name: "retrieval", component: () => import("./views/RetrievalView.vue") },
      { path: "evaluation", name: "evaluation", component: () => import("./views/EvaluationView.vue") },
      { path: "graph", name: "graph", component: () => import("./views/GraphView.vue") },
      { path: "admin", name: "admin", component: () => import("./views/AdminView.vue") },
    ],
  },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
