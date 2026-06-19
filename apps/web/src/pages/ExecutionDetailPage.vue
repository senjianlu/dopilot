<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { cancelExecution, getExecution } from "@/api/executions";
import type { ExecutionStatus, ExecutionView } from "@/api/types";
import LogViewer from "@/components/LogViewer.vue";

const { t } = useI18n();
const route = useRoute();

const executionId = computed(() => String(route.params.id));
const execution = ref<ExecutionView | null>(null);
const loading = ref(false);
const canceling = ref(false);
const errorMsg = ref("");

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

// Cancel only makes sense before the execution reaches a terminal state.
const cancelable = computed(() => {
  const status = execution.value?.status;
  return status === "queued" || status === "running" || status === "finalizing";
});

const paramsText = computed(() =>
  execution.value ? JSON.stringify(execution.value.params, null, 2) : "",
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    execution.value = await getExecution(executionId.value);
  } finally {
    loading.value = false;
  }
}

async function onCancel(): Promise<void> {
  errorMsg.value = "";
  canceling.value = true;
  try {
    execution.value = await cancelExecution(executionId.value);
  } catch {
    errorMsg.value = t("execution.cancelError");
  } finally {
    canceling.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div v-loading="loading" class="detail">
    <el-empty v-if="!execution" :description="t('execution.notFound')" />
    <template v-else>
      <el-card>
        <template #header>
          <div class="detail-header">
            <span>{{ t("execution.title") }}</span>
            <el-button
              v-if="cancelable"
              type="danger"
              :loading="canceling"
              @click="onCancel"
            >
              {{ t("execution.cancel") }}
            </el-button>
          </div>
        </template>
        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          :closable="false"
          show-icon
        />
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('execution.status')">
            <el-tag :type="statusTagType[execution.status]">
              {{ execution.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('execution.taskType')">
            {{ execution.task_type }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('execution.target')">
            {{ execution.target }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('execution.strategy')">
            {{ execution.node_strategy }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('execution.createdAt')">
            {{ execution.created_at ?? "-" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('execution.startedAt')">
            {{ execution.started_at ?? "-" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('execution.finishedAt')">
            {{ execution.finished_at ?? "-" }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card>
        <template #header>
          <span>{{ t("execution.params") }}</span>
        </template>
        <pre class="params">{{ paramsText }}</pre>
      </el-card>

      <el-card>
        <template #header>
          <span>{{ t("execution.attempts") }}</span>
        </template>
        <el-table :data="execution.attempts">
          <el-table-column :label="t('execution.attemptId')" prop="id" />
          <el-table-column :label="t('execution.agentId')" prop="agent_id" />
          <el-table-column :label="t('execution.nodeId')" prop="node_id" />
          <el-table-column :label="t('execution.endpoint')" prop="endpoint" />
          <el-table-column
            :label="t('execution.remoteJobId')"
            prop="remote_job_id"
          />
          <el-table-column :label="t('execution.status')" prop="status" />
          <el-table-column :label="t('execution.exitCode')" prop="exit_code" />
          <el-table-column
            :label="t('execution.errorCode')"
            prop="error_code"
          />
        </el-table>
      </el-card>

      <el-card>
        <LogViewer :execution-id="executionId" />
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.params {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
