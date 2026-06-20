import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
} from "vue-router";
import { registerUnauthorizedHandler } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import MainLayout from "@/layouts/MainLayout.vue";
import LoginPage from "@/pages/LoginPage.vue";
import DashboardPage from "@/pages/DashboardPage.vue";
import NodesPage from "@/pages/NodesPage.vue";
import BuildArtifactsPage from "@/pages/BuildArtifactsPage.vue";
import TemplatesPage from "@/pages/TemplatesPage.vue";
import SchedulesPage from "@/pages/SchedulesPage.vue";
import TasksPage from "@/pages/TasksPage.vue";
import TaskDetailPage from "@/pages/TaskDetailPage.vue";
import NotFound from "@/pages/NotFound.vue";

const routes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginPage },
  {
    path: "/",
    component: MainLayout,
    children: [
      { path: "", redirect: "/login" },
      { path: "dashboard", name: "dashboard", component: DashboardPage },
      { path: "nodes", name: "nodes", component: NodesPage },
      { path: "artifacts", name: "artifacts", component: BuildArtifactsPage },
      { path: "templates", name: "templates", component: TemplatesPage },
      { path: "schedules", name: "schedules", component: SchedulesPage },
      { path: "tasks", name: "tasks", component: TasksPage },
      {
        path: "tasks/:id",
        name: "task-detail",
        component: TaskDetailPage,
      },
    ],
  },
  { path: "/:pathMatch(.*)*", name: "not-found", component: NotFound },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Navigation guard: require a token for layout routes, unless auth is off.
router.beforeEach((to) => {
  const auth = useAuthStore();
  const isPublic = to.path === "/login" || to.name === "not-found";
  if (isPublic) {
    return true;
  }
  // Tolerant when auth is off: allow through even without a token.
  if (auth.isAuthOff) {
    return true;
  }
  if (!auth.isAuthenticated) {
    return { path: "/login" };
  }
  return true;
});

// Let the axios 401 handler redirect to /login without a circular import.
registerUnauthorizedHandler(() => {
  router.push("/login");
});

export default router;
