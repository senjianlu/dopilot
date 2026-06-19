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
import CrawlersPage from "@/pages/CrawlersPage.vue";
import ExecutionsPage from "@/pages/ExecutionsPage.vue";
import ExecutionDetailPage from "@/pages/ExecutionDetailPage.vue";
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
      { path: "crawlers", name: "crawlers", component: CrawlersPage },
      { path: "executions", name: "executions", component: ExecutionsPage },
      {
        path: "executions/:id",
        name: "execution-detail",
        component: ExecutionDetailPage,
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
