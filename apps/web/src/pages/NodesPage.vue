<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { deleteNode, listNodes, offlineNode, onlineNode } from "@/api/nodes";
import type { NodeInfo, NodeStatus } from "@/api/types";
import { badgeTagType, isOperable, nodeBadge } from "@/utils/nodeBadge";

const { t } = useI18n();
const nodes = ref<NodeInfo[]>([]);
const loading = ref(false);
const busyId = ref("");

const statusTagType: Record<NodeStatus, "success" | "warning" | "danger" | "info"> = {
  healthy: "success",
  degraded: "warning",
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

// Precedence badge label: deleted/offline win over the raw health status.
function badgeLabel(node: NodeInfo): string {
  const badge = nodeBadge(node);
  if (badge === "deleted") {
    return t("nodes.badgeDeleted");
  }
  if (badge === "offline") {
    return t("nodes.badgeOffline");
  }
  return node.status;
}

function badgeType(node: NodeInfo): "success" | "warning" | "danger" | "info" {
  return badgeTagType[nodeBadge(node)];
}

// id == null -> configured-but-unseen, no DB row, no scheduling ops yet.
function canOffline(node: NodeInfo): boolean {
  return isOperable(node) && node.scheduling_enabled;
}
function canOnline(node: NodeInfo): boolean {
  return isOperable(node) && !node.scheduling_enabled;
}
function canDelete(node: NodeInfo): boolean {
  return isOperable(node);
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    nodes.value = await listNodes();
  } finally {
    loading.value = false;
  }
}

// "Refresh" is just a fresh GET /nodes (the old POST /nodes/refresh is gone).
const onRefresh = load;

async function withBusy(id: string, fn: () => Promise<unknown>): Promise<void> {
  busyId.value = id;
  try {
    await fn();
    await load();
  } finally {
    busyId.value = "";
  }
}

async function onOffline(node: NodeInfo): Promise<void> {
  if (!node.id) return;
  await withBusy(node.id, () => offlineNode(node.id as string));
}
async function onOnline(node: NodeInfo): Promise<void> {
  if (!node.id) return;
  await withBusy(node.id, () => onlineNode(node.id as string));
}
async function onDelete(node: NodeInfo): Promise<void> {
  if (!node.id) return;
  await withBusy(node.id, () => deleteNode(node.id as string));
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
          <el-tag :type="badgeType(row as NodeInfo)">
            {{ badgeLabel(row as NodeInfo) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('health.status')">
        <template #default="{ row }">
          <el-tag :type="statusTagType[(row as NodeInfo).status]">
            {{ (row as NodeInfo).status }}
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
      <el-table-column :label="t('nodes.actions')" width="220">
        <template #default="{ row }">
          <el-button
            v-if="canOffline(row as NodeInfo)"
            type="warning"
            link
            :loading="busyId === (row as NodeInfo).id"
            @click="onOffline(row as NodeInfo)"
          >
            {{ t("nodes.offline") }}
          </el-button>
          <el-button
            v-if="canOnline(row as NodeInfo)"
            type="success"
            link
            :loading="busyId === (row as NodeInfo).id"
            @click="onOnline(row as NodeInfo)"
          >
            {{ t("nodes.online") }}
          </el-button>
          <el-button
            v-if="canDelete(row as NodeInfo)"
            type="danger"
            link
            :title="t('nodes.confirmDelete')"
            :loading="busyId === (row as NodeInfo).id"
            @click="onDelete(row as NodeInfo)"
          >
            {{ t("nodes.delete") }}
          </el-button>
        </template>
      </el-table-column>
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