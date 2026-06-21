// Pure node-selection helpers shared by the Templates and Schedules create
// dialogs. Kept framework-free so the branch logic is unit-testable without
// rendering the shadcn form.
import type { NodeInfo } from "@/lib/api/types";
import { nodeBadge } from "@/lib/nodeBadge";
import { NODE_BADGE_TONE, type Tone } from "@/components/features/status-badge";

export function nodeKey(node: NodeInfo): string {
  return (node.id ?? node.agent_id ?? node.endpoint) as string;
}

// Configured-but-unseen endpoints (id == null) never produced a DB row, so the
// backend can never resolve them as a `selected` target — exclude them.
export function isSeen(node: NodeInfo): boolean {
  return node.id != null;
}

// non-deleted + schedulable: eligible for the all/random involvement display.
export function schedulableNodes(nodes: NodeInfo[]): NodeInfo[] {
  return nodes.filter(
    (n) => isSeen(n) && !n.deleted_at && n.scheduling_enabled,
  );
}

// selectable for `selected`: non-deleted + non-offline (regardless of health).
export function selectableNodes(nodes: NodeInfo[]): NodeInfo[] {
  return nodes.filter(
    (n) => isSeen(n) && !n.deleted_at && n.scheduling_enabled,
  );
}

export function nodeByKey(
  nodes: NodeInfo[],
  key: string,
): NodeInfo | undefined {
  return nodes.find((n) => nodeKey(n) === key);
}

const FALLBACK_NODE = {
  status: "unknown" as const,
  scheduling_enabled: true,
  deleted_at: null,
};

// Traffic-light tone for a selected node id (colours the chip in the picker).
export function nodeToneForKey(nodes: NodeInfo[], key: string): Tone {
  return NODE_BADGE_TONE[nodeBadge(nodeByKey(nodes, key) ?? FALLBACK_NODE)];
}
