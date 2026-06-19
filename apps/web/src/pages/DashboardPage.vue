<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getHealth } from "@/api/health";
import type { HealthInfo } from "@/api/types";

const { t } = useI18n();
const health = ref<HealthInfo | null>(null);
const loading = ref(false);

const nodeSummary = computed(() => {
  const nodes = health.value?.nodes;
  if (!nodes) {
    return "-";
  }
  return `${nodes.online}/${nodes.total}`;
});

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
      <el-descriptions-item :label="t('health.nodesOnline')">
        {{ nodeSummary }}
      </el-descriptions-item>
      <el-descriptions-item :label="t('health.postgresql')">
        {{ health?.postgresql?.status ?? health?.database ?? "-" }}
        <span v-if="health?.postgresql?.version">
          · {{ health.postgresql.version }}
        </span>
      </el-descriptions-item>
      <el-descriptions-item :label="t('health.redis')">
        {{ health?.redis?.status ?? "-" }}
        <span v-if="health?.redis?.version">· {{ health.redis.version }}</span>
      </el-descriptions-item>
    </el-descriptions>
  </el-card>
</template>
