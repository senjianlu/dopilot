<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useAuthStore } from "@/stores/auth";
import LocaleSwitch from "@/components/LocaleSwitch.vue";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const activeMenu = computed(() => route.path);

function onLogout(): void {
  auth.logout();
  router.push("/login");
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="200px">
      <el-menu :default-active="activeMenu" router>
        <el-menu-item index="/dashboard">{{ t("nav.dashboard") }}</el-menu-item>
        <el-menu-item index="/nodes">{{ t("nav.nodes") }}</el-menu-item>
        <el-menu-item index="/placeholder" disabled>
          {{ t("errors.notImplemented") }}
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="app-name">{{ t("common.appName") }}</span>
        <div class="header-actions">
          <LocaleSwitch />
          <el-button text @click="onLogout">{{ t("common.logout") }}</el-button>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.app-name {
  font-weight: 600;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
