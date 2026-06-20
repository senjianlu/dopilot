<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getHealth } from "@/api/health";
import { getDailyTaskStats } from "@/api/stats";
import type { DailyTaskCount, HealthInfo } from "@/api/types";

const { t } = useI18n();
const health = ref<HealthInfo | null>(null);
const buckets = ref<DailyTaskCount[]>([]);
const loading = ref(false);

type Light = "green" | "yellow" | "red" | "gray";

interface ServiceRow {
  key: string;
  name: string;
  light: Light;
  notes: string;
}

const serviceRows = computed<ServiceRow[]>(() => {
  const h = health.value;
  const rows: ServiceRow[] = [];

  // Server: the dashboard rendered health, so the server responded.
  rows.push({
    key: "server",
    name: t("health.server"),
    light: h ? "green" : "gray",
    notes: h?.version ?? "-",
  });

  // Agent: schedulable-node scheduling health (server-computed).
  const agentStatus = (h?.agent?.status ?? "gray") as Light;
  rows.push({
    key: "agent",
    name: t("health.agent"),
    light: agentStatus,
    notes: h?.agent
      ? t("health.agentNotes", {
          healthy: h.agent.healthy,
          schedulable: h.agent.schedulable,
        })
      : "-",
  });

  // Redis: ok -> green, error -> red, disabled/unknown -> gray.
  const redisStatus = h?.redis?.status;
  let redisLight: Light = "gray";
  if (redisStatus === "ok") redisLight = "green";
  else if (redisStatus === "error") redisLight = "red";
  rows.push({
    key: "redis",
    name: t("health.redis"),
    light: redisLight,
    notes:
      redisStatus === "disabled" || !redisStatus
        ? t("health.redisDisabled")
        : (h?.redis?.version ?? redisStatus),
  });

  // PostgreSQL: ok -> green else red.
  const pg = h?.postgresql?.status ?? h?.database;
  rows.push({
    key: "postgresql",
    name: t("health.postgresql"),
    light: pg === "ok" ? "green" : "red",
    notes: h?.postgresql?.version ?? "-",
  });

  return rows;
});

const maxTasks = computed(() =>
  Math.max(1, ...buckets.value.map((b) => Math.max(b.tasks, b.executions))),
);

// Native SVG bar chart geometry — no chart dependency (brief constraint).
const chartWidth = 720;
const chartHeight = 160;
const barGap = 2;
const barWidth = computed(() =>
  buckets.value.length
    ? Math.max(2, (chartWidth - barGap) / buckets.value.length - barGap)
    : 0,
);

function barX(i: number): number {
  return barGap + i * (barWidth.value + barGap);
}
function barH(value: number): number {
  return Math.round((value / maxTasks.value) * (chartHeight - 20));
}
function barY(value: number): number {
  return chartHeight - barH(value);
}

const hasActivity = computed(() =>
  buckets.value.some((b) => b.tasks > 0 || b.executions > 0),
);

onMounted(async () => {
  loading.value = true;
  try {
    const [healthRes, statsRes] = await Promise.all([
      getHealth(),
      getDailyTaskStats(30),
    ]);
    health.value = healthRes;
    buckets.value = statsRes.buckets;
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="dashboard">
    <el-card v-loading="loading">
      <template #header>
        <span>{{ t("health.title") }}</span>
      </template>
      <el-table :data="serviceRows" :row-key="'key'">
        <el-table-column :label="t('health.service')" prop="name" />
        <el-table-column :label="t('health.status')" width="100">
          <template #default="{ row }">
            <span :class="['light', (row as ServiceRow).light]" />
          </template>
        </el-table-column>
        <el-table-column :label="t('health.notes')" prop="notes" />
      </el-table>
    </el-card>

    <el-card class="chart-card">
      <template #header>
        <span>{{ t("health.statsTitle") }}</span>
      </template>
      <div v-if="!hasActivity" class="chart-empty">
        {{ t("health.statsEmpty") }}
      </div>
      <svg
        v-else
        class="bar-chart"
        :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
        preserveAspectRatio="none"
        role="img"
      >
        <g v-for="(b, i) in buckets" :key="b.date">
          <rect
            class="bar-exec"
            :x="barX(i)"
            :y="barY(b.executions)"
            :width="barWidth"
            :height="barH(b.executions)"
          >
            <title>{{ b.date }} · {{ t("health.statsExecutions") }}: {{ b.executions }}</title>
          </rect>
          <rect
            class="bar-task"
            :x="barX(i)"
            :y="barY(b.tasks)"
            :width="barWidth"
            :height="barH(b.tasks)"
          >
            <title>{{ b.date }} · {{ t("health.statsTasks") }}: {{ b.tasks }}</title>
          </rect>
        </g>
      </svg>
      <div class="chart-legend">
        <span class="legend-item"><span class="swatch task" /> {{ t("health.statsTasks") }}</span>
        <span class="legend-item"><span class="swatch exec" /> {{ t("health.statsExecutions") }}</span>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.light {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
  animation: breathe 2s ease-in-out infinite;
}
.light.green {
  background: #67c23a;
}
.light.yellow {
  background: #e6a23c;
}
.light.red {
  background: #f56c6c;
}
.light.gray {
  background: #909399;
  animation: none;
}
@keyframes breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.25;
  }
}
.chart-card .bar-chart {
  width: 100%;
  height: 180px;
}
.bar-task {
  fill: #409eff;
}
.bar-exec {
  fill: #c6e2ff;
}
.chart-empty {
  color: var(--el-text-color-secondary);
  padding: 24px 0;
  text-align: center;
}
.chart-legend {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.swatch {
  width: 10px;
  height: 10px;
  display: inline-block;
  border-radius: 2px;
}
.swatch.task {
  background: #409eff;
}
.swatch.exec {
  background: #c6e2ff;
}
</style>