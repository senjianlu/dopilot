<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { deleteNode, listNodes, offlineNode, onlineNode } from "@/api/nodes";
import type { NodeInfo } from "@/api/types";
import { badgeTagType, isOperable, nodeBadge } from "@/utils/nodeBadge";
import { confirmAction } from "@/utils/confirm";

const { t } = useI18n();
const nodes = ref<NodeInfo[]>([]);
const loading = ref(false);
const busyId = ref("");

// Phase 1.8.2: a single status column. The badge already folds the backend
// aggregate `node.status` (heartbeat freshness + Redis + command consumer) and
// the offline/deleted precedence into one displayed state.
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

// Phase 1.8.2: capability tags. Only `scrapy` is expected green in normal
// deployments; `script` / `docker` are reserved and stay gray until supported.
const CAPABILITY_KEYS = ["scrapy", "script", "docker"] as const;
function capActive(node: NodeInfo, key: string): boolean {
  return node.capabilities?.[key] === true;
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
  const ok = await confirmAction({
    title: t("confirm.title"),
    message: t("nodes.confirmOffline", { node: node.agent_id ?? node.endpoint }),
    confirmText: t("confirm.confirm"),
    cancelText: t("confirm.cancel"),
  });
  if (!ok) return;
  await withBusy(node.id, () => offlineNode(node.id as string));
}
async function onOnline(node: NodeInfo): Promise<void> {
  if (!node.id) return;
  await withBusy(node.id, () => onlineNode(node.id as string));
}
async function onDelete(node: NodeInfo): Promise<void> {
  if (!node.id) return;
  const ok = await confirmAction({
    title: t("confirm.title"),
    message: t("nodes.confirmDelete", { node: node.agent_id ?? node.endpoint }),
    confirmText: t("confirm.confirm"),
    cancelText: t("confirm.cancel"),
  });
  if (!ok) return;
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
    <el-table :data="nodes" :empty-text="t('nodes.empty')" data-testid="nodes-table">
      <el-table-column :label="t('nodes.endpoint')" prop="endpoint" />
      <el-table-column :label="t('nodes.agentId')">
        <template #default="{ row }">
          <span
            class="node-agent-id"
            :data-testid="`node-agent-${(row as NodeInfo).agent_id}`"
          >
            {{ (row as NodeInfo).agent_id }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('nodes.status')">
        <template #default="{ row }">
          <el-tag
            :type="badgeType(row as NodeInfo)"
            :data-testid="`node-badge-${(row as NodeInfo).agent_id}`"
          >
            {{ badgeLabel(row as NodeInfo) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('nodes.capabilities')">
        <template #default="{ row }">
          <span class="node-caps">
            <el-tag
              v-for="cap in CAPABILITY_KEYS"
              :key="cap"
              :type="capActive(row as NodeInfo, cap) ? 'success' : 'info'"
              :data-testid="`node-cap-${(row as NodeInfo).agent_id}-${cap}`"
              disable-transitions
            >
              {{ cap }}
            </el-tag>
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('nodes.lastSeen')" prop="last_seen_at" />
      <el-table-column :label="t('nodes.actions')" width="220">
        <template #default="{ row }">
          <el-button
            v-if="canOffline(row as NodeInfo)"
            type="warning"
            link
            :data-testid="`node-offline-${(row as NodeInfo).agent_id}`"
            :loading="busyId === (row as NodeInfo).id"
            @click="onOffline(row as NodeInfo)"
          >
            {{ t("nodes.offline") }}
          </el-button>
          <el-button
            v-if="canOnline(row as NodeInfo)"
            type="success"
            link
            :data-testid="`node-online-${(row as NodeInfo).agent_id}`"
            :loading="busyId === (row as NodeInfo).id"
            @click="onOnline(row as NodeInfo)"
          >
            {{ t("nodes.online") }}
          </el-button>
          <el-button
            v-if="canDelete(row as NodeInfo)"
            type="danger"
            link
            :data-testid="`node-delete-${(row as NodeInfo).agent_id}`"
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
.node-caps {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
