<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { listNodes, refreshNodes } from "@/api/nodes";
import type { NodeInfo, NodeStatus } from "@/api/types";

const { t } = useI18n();
const nodes = ref<NodeInfo[]>([]);
const loading = ref(false);

const statusTagType: Record<NodeStatus, "success" | "danger" | "info"> = {
  healthy: "success",
  unhealthy: "danger",
  unknown: "info",
};

type ScrapydHealth = "running" | "stopped" | "unknown";

// Read the agent-reported scrapyd subprocess health out of health.scrapyd.
function scrapydHealthOf(node: NodeInfo): ScrapydHealth {
  const scrapyd = node.health?.scrapyd as
    | { running?: unknown }
    | undefined
    | null;
  if (scrapyd == null || scrapyd.running == null) {
    return "unknown";
  }
  return scrapyd.running ? "running" : "stopped";
}

const scrapydTagType: Record<ScrapydHealth, "success" | "danger" | "info"> = {
  running: "success",
  stopped: "danger",
  unknown: "info",
};

const scrapydLabel: Record<ScrapydHealth, string> = {
  running: "nodes.scrapydRunning",
  stopped: "nodes.scrapydStopped",
  unknown: "nodes.scrapydUnknown",
};

async function load(): Promise<void> {
  loading.value = true;
  try {
    nodes.value = await listNodes();
  } finally {
    loading.value = false;
  }
}

async function onRefresh(): Promise<void> {
  loading.value = true;
  try {
    nodes.value = await refreshNodes();
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="nodes-header">
        <span>{{ t("nodes.title") }}</span>
        <el-button type="primary" @click="onRefresh">
          {{ t("nodes.refresh") }}
        </el-button>
      </div>
    </template>
    <el-table :data="nodes" :empty-text="t('nodes.empty')">
      <el-table-column :label="t('nodes.endpoint')" prop="endpoint" />
      <el-table-column :label="t('nodes.agentId')" prop="agent_id" />
      <el-table-column :label="t('nodes.status')">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status as NodeStatus]">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('nodes.scrapyd')">
        <template #default="{ row }">
          <el-tag :type="scrapydTagType[scrapydHealthOf(row as NodeInfo)]">
            {{ t(scrapydLabel[scrapydHealthOf(row as NodeInfo)]) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('nodes.lastSeen')" prop="last_seen_at" />
    </el-table>
  </el-card>
</template>

<style scoped>
.nodes-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
