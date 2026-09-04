import { defineStore } from "pinia";
import { computed, ref } from "vue";

export type UserRole = "end_user" | "knowledge_expert" | "algorithm_engineer" | "admin";

const ROLE_MENUS: Record<UserRole, string[]> = {
  end_user: ["dashboard", "chat"],
  knowledge_expert: ["dashboard", "chat", "kb", "documents", "review", "catalog"],
  algorithm_engineer: [
    "dashboard",
    "chat",
    "kb",
    "documents",
    "review",
    "catalog",
    "strategies",
    "prompts",
    "retrieval",
    "evaluation",
  ],
  admin: [
    "dashboard",
    "chat",
    "kb",
    "documents",
    "review",
    "catalog",
    "strategies",
    "prompts",
    "retrieval",
    "evaluation",
    "graph",
    "admin",
  ],
};

export const useSession = defineStore("session", () => {
  const username = ref(localStorage.getItem("akrag_user") || "admin");
  const role = ref<UserRole>((localStorage.getItem("akrag_role") as UserRole) || "admin");

  const allowed = computed(() => ROLE_MENUS[role.value]);

  function setUser(name: string, nextRole: UserRole) {
    username.value = name;
    role.value = nextRole;
    localStorage.setItem("akrag_user", name);
    localStorage.setItem("akrag_role", nextRole);
  }

  return { username, role, allowed, setUser };
});
