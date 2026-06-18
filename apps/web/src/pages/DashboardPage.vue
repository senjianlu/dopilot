<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getHealth } from "@/api/health";
import type { HealthInfo } from "@/api/types";

const { t } = useI18n();
const health = ref<HealthInfo | null>(null);
const loading = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    health.value = await getHealth();
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <span>{{ t("health.title") }}</span>
    </template>
    <el-descriptions :column="1" border>
      <el-descriptions-item :label="t('health.status')">
        {{ health?.status ?? "-" }}
      </el-descriptions-item>
      <el-descriptions-item :label="t('health.version')">
        {{ health?.version ?? "-" }}
      </el-descriptions-item>
      <el-descriptions-item :label="t('health.database')">
        {{ health?.database ?? "-" }}
      </el-descriptions-item>
    </el-descriptions>
  </el-card>
</template>
