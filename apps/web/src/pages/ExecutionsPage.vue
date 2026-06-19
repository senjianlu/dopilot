<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { listExecutions } from "@/api/executions";
import type { ExecutionStatus, ExecutionSummary } from "@/api/types";

const { t } = useI18n();
const executions = ref<ExecutionSummary[]>([]);
const loading = ref(false);

const statusTagType: Record<
  ExecutionStatus,
  "success" | "danger" | "info" | "warning" | "primary"
> = {
  queued: "info",
  running: "primary",
  finalizing: "warning",
  complete: "success",
  failed: "danger",
  canceled: "info",
  lost: "danger",
  no_target: "warning",
};

async function load(): Promise<void> {
  loading.value = true;
  try {
    executions.value = await listExecutions();
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="executions-header">
        <span>{{ t("executions.title") }}</span>
        <el-button type="primary" @click="load">
          {{ t("executions.refresh") }}
        </el-button>
      </div>
    </template>
    <el-table :data="executions" :empty-text="t('executions.empty')">
      <el-table-column :label="t('executions.status')">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status as ExecutionStatus]">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('executions.target')" prop="target" />
      <el-table-column :label="t('executions.taskType')" prop="task_type" />
      <el-table-column :label="t('executions.strategy')" prop="node_strategy" />
      <el-table-column :label="t('executions.attempts')" prop="attempt_count" />
      <el-table-column :label="t('executions.createdAt')" prop="created_at" />
      <el-table-column :label="t('executions.startedAt')" prop="started_at" />
      <el-table-column :label="t('executions.finishedAt')" prop="finished_at" />
      <el-table-column :label="t('executions.id')">
        <template #default="{ row }">
          <router-link
            :to="{ name: 'execution-detail', params: { id: row.id } }"
          >
            {{ t("executions.view") }}
          </router-link>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.executions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
