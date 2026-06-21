"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
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
import { Alert, AlertTitle } from "@/components/ui/alert";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { ToneBadge, type Tone } from "@/components/features/status-badge";
import { LogViewer } from "@/components/features/log-viewer";
import { cancelTask, getTask } from "@/lib/api/tasks";
import { markTaskLost } from "@/lib/api/maintenance";
import type { TaskStatus, TaskView } from "@/lib/api/types";
import { useConfirm } from "@/hooks/use-confirm";

const STATUS_TONE: Record<TaskStatus, Tone> = {
  queued: "gray",
  running: "amber",
  finalizing: "amber",
  complete: "green",
  failed: "red",
  canceled: "gray",
  lost: "red",
  no_target: "amber",
};

function TaskDetail() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const searchParams = useSearchParams();
  const taskId = searchParams.get("id") ?? "";

  const [task, setTask] = React.useState<TaskView | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [canceling, setCanceling] = React.useState(false);
  const [markingLost, setMarkingLost] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState("");

  const load = React.useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      setTask(await getTask(taskId));
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const cancelable =
    task?.status === "queued" ||
    task?.status === "running" ||
    task?.status === "finalizing";

  async function onCancel() {
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("task.confirmCancel"),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    setErrorMsg("");
    setCanceling(true);
    try {
      setTask(await cancelTask(taskId));
    } catch {
      setErrorMsg(t("task.cancelError"));
    } finally {
      setCanceling(false);
    }
  }

  async function onMarkLost() {
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("task.confirmMarkLost"),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    setErrorMsg("");
    setMarkingLost(true);
    try {
      await markTaskLost(taskId);
      await load();
    } catch {
      setErrorMsg(t("task.markLostError"));
    } finally {
      setMarkingLost(false);
    }
  }

  return (
    <div className="flex flex-col gap-4" data-testid="task-detail">
      {!task ? (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>{loading ? "…" : t("task.notFound")}</EmptyTitle>
            <EmptyDescription className="sr-only">
              {t("task.notFound")}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>{t("task.title")}</CardTitle>
              {cancelable && (
                <CardAction>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      data-testid="task-mark-lost"
                      disabled={markingLost}
                      onClick={onMarkLost}
                    >
                      {markingLost && <Spinner data-icon="inline-start" />}
                      {t("task.markLost")}
                    </Button>
                    <Button
                      variant="destructive"
                      data-testid="task-cancel"
                      disabled={canceling}
                      onClick={onCancel}
                    >
                      {canceling && <Spinner data-icon="inline-start" />}
                      {t("task.cancel")}
                    </Button>
                  </div>
                </CardAction>
              )}
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {errorMsg && (
                <Alert variant="destructive">
                  <AlertTitle>{errorMsg}</AlertTitle>
                </Alert>
              )}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted-foreground">{t("task.status")}</dt>
                <dd>
                  <ToneBadge
                    tone={STATUS_TONE[task.status]}
                    data-testid="task-status"
                  >
                    {task.status}
                  </ToneBadge>
                </dd>
                <dt className="text-muted-foreground">
                  {t("task.artifactType")}
                </dt>
                <dd>{task.artifact_type}</dd>
                <dt className="text-muted-foreground">{t("task.target")}</dt>
                <dd className="break-all">{task.target}</dd>
                <dt className="text-muted-foreground">{t("task.strategy")}</dt>
                <dd>{task.node_strategy}</dd>
                <dt className="text-muted-foreground">{t("task.createdAt")}</dt>
                <dd>{task.created_at ?? "-"}</dd>
                <dt className="text-muted-foreground">{t("task.startedAt")}</dt>
                <dd>{task.started_at ?? "-"}</dd>
                <dt className="text-muted-foreground">{t("task.finishedAt")}</dt>
                <dd>{task.finished_at ?? "-"}</dd>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("task.buildArtifact")}</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="m-0 text-xs whitespace-pre-wrap break-all">
                {JSON.stringify(task.build_artifact, null, 2)}
              </pre>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("task.params")}</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="m-0 text-xs whitespace-pre-wrap break-all">
                {JSON.stringify(task.params, null, 2)}
              </pre>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("task.executions")}</CardTitle>
            </CardHeader>
            <CardContent>
              <Table data-testid="task-executions">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("task.executionId")}</TableHead>
                    <TableHead>{t("task.agentId")}</TableHead>
                    <TableHead>{t("task.nodeId")}</TableHead>
                    <TableHead>{t("task.endpoint")}</TableHead>
                    <TableHead>{t("task.remoteJobId")}</TableHead>
                    <TableHead>{t("task.status")}</TableHead>
                    <TableHead>{t("task.exitCode")}</TableHead>
                    <TableHead>{t("task.errorCode")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {task.executions.map((ex) => (
                    <TableRow key={ex.id}>
                      <TableCell>{ex.id}</TableCell>
                      <TableCell>
                        <span data-testid={`execution-agent-${ex.agent_id}`}>
                          {ex.agent_id}
                        </span>
                      </TableCell>
                      <TableCell>{ex.node_id ?? "-"}</TableCell>
                      <TableCell>{ex.endpoint ?? "-"}</TableCell>
                      <TableCell>{ex.remote_job_id ?? "-"}</TableCell>
                      <TableCell>{ex.status}</TableCell>
                      <TableCell>{ex.exit_code ?? "-"}</TableCell>
                      <TableCell>{ex.error_code ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <LogViewer taskId={taskId} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

export default function TaskDetailPage() {
  // Static export prerenders this route; useSearchParams must sit under Suspense.
  return (
    <React.Suspense fallback={<div data-testid="task-detail" />}>
      <TaskDetail />
    </React.Suspense>
  );
}
