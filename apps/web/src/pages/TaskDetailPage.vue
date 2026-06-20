<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { cancelTask, getTask } from "@/api/tasks";
import type { TaskStatus, TaskView } from "@/api/types";
import LogViewer from "@/components/LogViewer.vue";

const { t } = useI18n();
const route = useRoute();

const taskId = computed(() => String(route.params.id));
const task = ref<TaskView | null>(null);
const loading = ref(false);
const canceling = ref(false);
const errorMsg = ref("");

const statusTagType: Record<
  TaskStatus,
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

// Cancel only makes sense before the task reaches a terminal state.
const cancelable = computed(() => {
  const status = task.value?.status;
  return status === "queued" || status === "running" || status === "finalizing";
});

const paramsText = computed(() =>
  task.value ? JSON.stringify(task.value.params, null, 2) : "",
);

const buildArtifactText = computed(() =>
  task.value ? JSON.stringify(task.value.build_artifact, null, 2) : "",
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    task.value = await getTask(taskId.value);
  } finally {
    loading.value = false;
  }
}

async function onCancel(): Promise<void> {
  errorMsg.value = "";
  canceling.value = true;
  try {
    task.value = await cancelTask(taskId.value);
  } catch {
    errorMsg.value = t("task.cancelError");
  } finally {
    canceling.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div v-loading="loading" class="detail" data-testid="task-detail">
    <el-empty v-if="!task" :description="t('task.notFound')" />
    <template v-else>
      <el-card>
        <template #header>
          <div class="detail-header">
            <span>{{ t("task.title") }}</span>
            <el-button
              v-if="cancelable"
              type="danger"
              :loading="canceling"
              @click="onCancel"
            >
              {{ t("task.cancel") }}
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
          <el-descriptions-item :label="t('task.status')">
            <el-tag :type="statusTagType[task.status]" data-testid="task-status">
              {{ task.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('task.artifactType')">
            {{ task.artifact_type }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('task.target')">
            {{ task.target }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('task.strategy')">
            {{ task.node_strategy }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('task.createdAt')">
            {{ task.created_at ?? "-" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('task.startedAt')">
            {{ task.started_at ?? "-" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('task.finishedAt')">
            {{ task.finished_at ?? "-" }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card>
        <template #header>
          <span>{{ t("task.buildArtifact") }}</span>
        </template>
        <pre class="params">{{ buildArtifactText }}</pre>
      </el-card>

      <el-card>
        <template #header>
          <span>{{ t("task.params") }}</span>
        </template>
        <pre class="params">{{ paramsText }}</pre>
      </el-card>

      <el-card>
        <template #header>
          <span>{{ t("task.executions") }}</span>
        </template>
        <el-table :data="task.executions" data-testid="task-executions">
          <el-table-column :label="t('task.executionId')" prop="id" />
          <el-table-column :label="t('task.agentId')">
            <template #default="{ row }">
              <span :data-testid="`execution-agent-${row.agent_id}`">
                {{ row.agent_id }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="t('task.nodeId')" prop="node_id" />
          <el-table-column :label="t('task.endpoint')" prop="endpoint" />
          <el-table-column
            :label="t('task.remoteJobId')"
            prop="remote_job_id"
          />
          <el-table-column :label="t('task.status')" prop="status" />
          <el-table-column :label="t('task.exitCode')" prop="exit_code" />
          <el-table-column :label="t('task.errorCode')" prop="error_code" />
        </el-table>
      </el-card>

      <el-card>
        <LogViewer :task-id="taskId" />
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
