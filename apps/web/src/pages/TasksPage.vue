<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { listTasks } from "@/api/tasks";
import {
  TASK_PAGE_SIZES,
  type TaskPageSize,
  type TaskStatus,
  type TaskSummary,
} from "@/api/types";

const { t } = useI18n();
const tasks = ref<TaskSummary[]>([]);
const loading = ref(false);
const page = ref(1);
const pageSize = ref<TaskPageSize>(20);
const total = ref(0);
const spiders = ref<string[]>([]);
// "" is the "all spiders" state.
const spider = ref("");
const pageSizes = TASK_PAGE_SIZES;

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

// Choose the closest allowed page size from the visible table height. The
// backend only accepts 5/10/20/50/100, so snap to the nearest of those.
function pickPageSizeFromHeight(): TaskPageSize {
  const rowPx = 48;
  const chromePx = 320;
  const avail = (typeof window !== "undefined" ? window.innerHeight : 800) - chromePx;
  const target = Math.max(1, Math.floor(avail / rowPx));
  let best: TaskPageSize = pageSizes[0];
  for (const size of pageSizes) {
    if (Math.abs(size - target) < Math.abs(best - target)) {
      best = size;
    }
  }
  return best;
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await listTasks({
      page: page.value,
      pageSize: pageSize.value,
      spider: spider.value || null,
    });
    tasks.value = res.tasks;
    total.value = res.total;
    page.value = res.page;
    pageSize.value = res.page_size as TaskPageSize;
    spiders.value = res.spiders;
  } finally {
    loading.value = false;
  }
}

function onSpiderChange(): void {
  page.value = 1;
  void load();
}

function onPageChange(next: number): void {
  page.value = next;
  void load();
}

function onSizeChange(size: number): void {
  pageSize.value = size as TaskPageSize;
  page.value = 1;
  void load();
}

onMounted(() => {
  pageSize.value = pickPageSizeFromHeight();
  void load();
});
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="tasks-header">
        <span>{{ t("tasks.title") }}</span>
        <div class="tasks-actions">
          <el-select
            v-model="spider"
            class="spider-filter"
            @change="onSpiderChange"
          >
            <el-option :label="t('tasks.spiderAll')" value="" />
            <el-option
              v-for="s in spiders"
              :key="s"
              :label="s"
              :value="s"
            />
          </el-select>
          <el-button type="primary" @click="load">
            {{ t("tasks.refresh") }}
          </el-button>
        </div>
      </div>
    </template>
    <el-table :data="tasks" :empty-text="t('tasks.empty')" data-testid="tasks-table">
      <el-table-column :label="t('tasks.status')">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status as TaskStatus]">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('tasks.target')" prop="target" />
      <el-table-column :label="t('tasks.spider')" prop="spider" />
      <el-table-column :label="t('tasks.artifactType')" prop="artifact_type" />
      <el-table-column :label="t('tasks.strategy')" prop="node_strategy" />
      <el-table-column :label="t('tasks.executions')" prop="execution_count" />
      <el-table-column :label="t('tasks.createdAt')" prop="created_at" />
      <el-table-column :label="t('tasks.startedAt')" prop="started_at" />
      <el-table-column :label="t('tasks.finishedAt')" prop="finished_at" />
      <el-table-column :label="t('tasks.id')">
        <template #default="{ row }">
          <router-link
            :to="{ name: 'task-detail', params: { id: row.id } }"
            :data-testid="`task-view-${row.id}`"
            class="task-view-link"
          >
            {{ t("tasks.view") }}
          </router-link>
        </template>
      </el-table-column>
    </el-table>
    <div class="tasks-pagination">
      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="pageSizes as unknown as number[]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </el-card>
</template>

<style scoped>
.tasks-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tasks-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.spider-filter {
  min-width: 160px;
}
.tasks-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
