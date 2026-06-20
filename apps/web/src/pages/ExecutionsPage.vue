<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { listExecutions } from "@/api/executions";
import {
  EXECUTION_PAGE_SIZES,
  type ExecutionPageSize,
  type ExecutionStatus,
  type ExecutionSummary,
} from "@/api/types";

const { t } = useI18n();
const executions = ref<ExecutionSummary[]>([]);
const loading = ref(false);
const page = ref(1);
const pageSize = ref<ExecutionPageSize>(20);
const total = ref(0);
const spiders = ref<string[]>([]);
// "" is the "all spiders" state.
const spider = ref("");
const pageSizes = EXECUTION_PAGE_SIZES;

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

// Choose the closest allowed page size from the visible table height. The
// backend only accepts 5/10/20/50/100, so snap to the nearest of those.
function pickPageSizeFromHeight(): ExecutionPageSize {
  const rowPx = 48;
  const chromePx = 320;
  const avail = (typeof window !== "undefined" ? window.innerHeight : 800) - chromePx;
  const target = Math.max(1, Math.floor(avail / rowPx));
  let best: ExecutionPageSize = pageSizes[0];
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
    const res = await listExecutions({
      page: page.value,
      pageSize: pageSize.value,
      spider: spider.value || null,
    });
    executions.value = res.executions;
    total.value = res.total;
    page.value = res.page;
    pageSize.value = res.page_size as ExecutionPageSize;
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
  pageSize.value = size as ExecutionPageSize;
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
      <div class="executions-header">
        <span>{{ t("executions.title") }}</span>
        <div class="executions-actions">
          <el-select
            v-model="spider"
            class="spider-filter"
            @change="onSpiderChange"
          >
            <el-option :label="t('executions.spiderAll')" value="" />
            <el-option
              v-for="s in spiders"
              :key="s"
              :label="s"
              :value="s"
            />
          </el-select>
          <el-button type="primary" @click="load">
            {{ t("executions.refresh") }}
          </el-button>
        </div>
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
      <el-table-column :label="t('executions.spider')" prop="spider" />
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
    <div class="executions-pagination">
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
.executions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.executions-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.spider-filter {
  min-width: 160px;
}
.executions-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>