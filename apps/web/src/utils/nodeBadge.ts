// Phase 1.7.1: node badge precedence (shared by Nodes + Templates pages).
//   deleted = gray, offline = red, healthy online = green,
//   degraded/unhealthy/unknown online = yellow.
import type { NodeBadge, NodeInfo } from "@/api/types";

export type ElTagType = "success" | "warning" | "danger" | "info";

export function nodeBadge(node: Pick<
  NodeInfo,
  "status" | "scheduling_enabled" | "deleted_at"
>): NodeBadge {
  if (node.deleted_at) {
    return "deleted";
  }
  if (!node.scheduling_enabled) {
    return "offline";
  }
  if (node.status === "healthy") {
    return "healthy";
  }
  if (node.status === "unknown") {
    return "unknown";
  }
  return "warning";
}

export const badgeTagType: Record<NodeBadge, ElTagType> = {
  deleted: "info", // gray
  offline: "danger", // red
  healthy: "success", // green
  warning: "warning", // yellow
  unknown: "warning", // yellow (online but unknown health)
};

export function isOperable(node: Pick<NodeInfo, "id" | "deleted_at">): boolean {
  // Configured-but-unseen endpoints (id == null) have no DB row to act on.
  return node.id != null && !node.deleted_at;
}