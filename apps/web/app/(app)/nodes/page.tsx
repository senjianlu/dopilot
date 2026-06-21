"use client";

import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  NODE_BADGE_TONE,
  ToneBadge,
} from "@/components/features/status-badge";
import { deleteNode, listNodes, offlineNode, onlineNode } from "@/lib/api/nodes";
import type { NodeInfo } from "@/lib/api/types";
import { isOperable, nodeBadge } from "@/lib/nodeBadge";
import { useConfirm } from "@/hooks/use-confirm";

const CAPABILITY_KEYS = ["scrapy", "script", "docker"] as const;

export default function NodesPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [nodes, setNodes] = React.useState<NodeInfo[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [busyId, setBusyId] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setNodes(await listNodes());
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  function badgeLabel(node: NodeInfo): string {
    const badge = nodeBadge(node);
    if (badge === "deleted") return t("nodes.badgeDeleted");
    if (badge === "offline") return t("nodes.badgeOffline");
    return node.status;
  }

  function capActive(node: NodeInfo, key: string): boolean {
    return node.capabilities?.[key] === true;
  }

  function canOffline(node: NodeInfo): boolean {
    return isOperable(node) && node.scheduling_enabled;
  }
  function canOnline(node: NodeInfo): boolean {
    return isOperable(node) && !node.scheduling_enabled;
  }
  function canDelete(node: NodeInfo): boolean {
    return isOperable(node);
  }

  async function withBusy(id: string, fn: () => Promise<unknown>) {
    setBusyId(id);
    try {
      await fn();
      await load();
    } finally {
      setBusyId("");
    }
  }

  async function onOffline(node: NodeInfo) {
    if (!node.id) return;
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("nodes.confirmOffline", {
        node: node.agent_id ?? node.endpoint,
      }),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    await withBusy(node.id, () => offlineNode(node.id as string));
  }

  async function onOnline(node: NodeInfo) {
    if (!node.id) return;
    await withBusy(node.id, () => onlineNode(node.id as string));
  }

  async function onDelete(node: NodeInfo) {
    if (!node.id) return;
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("nodes.confirmDelete", {
        node: node.agent_id ?? node.endpoint,
      }),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    await withBusy(node.id, () => deleteNode(node.id as string));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("nodes.title")}</CardTitle>
        <CardAction>
          <Button onClick={load}>{t("nodes.refresh")}</Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table data-testid="nodes-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("nodes.endpoint")}</TableHead>
              <TableHead>{t("nodes.agentId")}</TableHead>
              <TableHead>{t("nodes.status")}</TableHead>
              <TableHead>{t("nodes.capabilities")}</TableHead>
              <TableHead>{t("nodes.lastSeen")}</TableHead>
              <TableHead className="text-right">{t("nodes.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {nodes.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-muted-foreground text-center"
                >
                  {loading ? "…" : t("nodes.empty")}
                </TableCell>
              </TableRow>
            ) : (
              nodes.map((node) => (
                <TableRow key={node.id ?? node.endpoint}>
                  <TableCell>{node.endpoint}</TableCell>
                  <TableCell>
                    <span data-testid={`node-agent-${node.agent_id}`}>
                      {node.agent_id}
                    </span>
                  </TableCell>
                  <TableCell>
                    <ToneBadge
                      tone={NODE_BADGE_TONE[nodeBadge(node)]}
                      data-testid={`node-badge-${node.agent_id}`}
                    >
                      {badgeLabel(node)}
                    </ToneBadge>
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex flex-wrap gap-1">
                      {CAPABILITY_KEYS.map((cap) => (
                        <ToneBadge
                          key={cap}
                          tone={capActive(node, cap) ? "green" : "gray"}
                          data-testid={`node-cap-${node.agent_id}-${cap}`}
                        >
                          {cap}
                        </ToneBadge>
                      ))}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {node.last_seen_at ?? "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    {canOffline(node) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`node-offline-${node.agent_id}`}
                        disabled={busyId === node.id}
                        onClick={() => onOffline(node)}
                      >
                        {busyId === node.id && (
                          <Spinner data-icon="inline-start" />
                        )}
                        {t("nodes.offline")}
                      </Button>
                    )}
                    {canOnline(node) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`node-online-${node.agent_id}`}
                        disabled={busyId === node.id}
                        onClick={() => onOnline(node)}
                      >
                        {busyId === node.id && (
                          <Spinner data-icon="inline-start" />
                        )}
                        {t("nodes.online")}
                      </Button>
                    )}
                    {canDelete(node) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        data-testid={`node-delete-${node.agent_id}`}
                        disabled={busyId === node.id}
                        onClick={() => onDelete(node)}
                      >
                        {busyId === node.id && (
                          <Spinner data-icon="inline-start" />
                        )}
                        {t("nodes.delete")}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
