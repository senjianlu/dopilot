"use client";

import * as React from "react";
import Link from "next/link";
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
} from "@/components/ui/pagination";
import { ToneBadge, type Tone } from "@/components/features/status-badge";
import { listTasks } from "@/lib/api/tasks";
import { formatDateTime } from "@/lib/format";
import {
  TASK_PAGE_SIZES,
  type BuildArtifactOption,
  type TaskPageSize,
  type TaskStatus,
  type TaskSummary,
} from "@/lib/api/types";

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

// "All build artifacts" sentinel (Radix Select forbids an empty-string value).
// The list filters by build artifact: the value is a build_artifact_id sent to
// the backend, and the options come from the tasks' distinct build artifacts.
const BUILD_ALL = "__all__";

// "All statuses" sentinel (same Radix empty-string constraint). The backend
// validates a concrete status against its known task statuses.
const STATUS_ALL = "__all__";
const STATUS_OPTIONS: TaskStatus[] = [
  "queued",
  "running",
  "finalizing",
  "complete",
  "failed",
  "canceled",
  "lost",
  "no_target",
];

// A build artifact's display text in the row/dropdown (label, then name, id).
function buildArtifactText(art: BuildArtifactOption): string {
  return art.label || art.name || art.id;
}

function pickPageSizeFromHeight(): TaskPageSize {
  const rowPx = 48;
  const chromePx = 320;
  const avail =
    (typeof window !== "undefined" ? window.innerHeight : 800) - chromePx;
  const target = Math.max(1, Math.floor(avail / rowPx));
  let best: TaskPageSize = TASK_PAGE_SIZES[0];
  for (const size of TASK_PAGE_SIZES) {
    if (Math.abs(size - target) < Math.abs(best - target)) {
      best = size;
    }
  }
  return best;
}

export default function TasksPage() {
  const { t } = useTranslation();
  const [tasks, setTasks] = React.useState<TaskSummary[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [pageSize, setPageSize] = React.useState<TaskPageSize>(20);
  const [total, setTotal] = React.useState(0);
  const [builds, setBuilds] = React.useState<BuildArtifactOption[]>([]);
  const [buildFilter, setBuildFilter] = React.useState(BUILD_ALL);
  const [statusFilter, setStatusFilter] = React.useState(STATUS_ALL);

  const load = React.useCallback(
    async (
      nextPage: number,
      size: TaskPageSize,
      buildFilterValue: string,
      statusFilterValue: string,
    ) => {
      setLoading(true);
      try {
        const res = await listTasks({
          page: nextPage,
          pageSize: size,
          buildArtifactId:
            buildFilterValue === BUILD_ALL ? null : buildFilterValue,
          status:
            statusFilterValue === STATUS_ALL
              ? null
              : (statusFilterValue as TaskStatus),
        });
        setTasks(res.tasks);
        setTotal(res.total);
        setPage(res.page);
        setPageSize(res.page_size as TaskPageSize);
        setBuilds(res.build_artifacts);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  React.useEffect(() => {
    const size = pickPageSizeFromHeight();
    setPageSize(size);
    void load(1, size, BUILD_ALL, STATUS_ALL);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Changing either filter resets to page 1; pagination/size/refresh keep both.
  function onBuildChange(value: string) {
    setBuildFilter(value);
    void load(1, pageSize, value, statusFilter);
  }

  function onStatusChange(value: string) {
    setStatusFilter(value);
    void load(1, pageSize, buildFilter, value);
  }

  function onSizeChange(value: string) {
    const size = Number(value) as TaskPageSize;
    void load(1, size, buildFilter, statusFilter);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tasks.title")}</CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            <Select value={statusFilter} onValueChange={onStatusChange}>
              <SelectTrigger
                className="min-w-36"
                data-testid="tasks-status-filter"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={STATUS_ALL}>
                    {t("tasks.statusAll")}
                  </SelectItem>
                  {STATUS_OPTIONS.map((status) => (
                    <SelectItem key={status} value={status}>
                      {status}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select value={buildFilter} onValueChange={onBuildChange}>
              <SelectTrigger
                className="min-w-40"
                data-testid="tasks-build-filter"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={BUILD_ALL}>
                    {t("tasks.buildArtifactAll")}
                  </SelectItem>
                  {builds.map((art) => (
                    <SelectItem key={art.id} value={art.id}>
                      {buildArtifactText(art)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              onClick={() => load(page, pageSize, buildFilter, statusFilter)}
            >
              {t("tasks.refresh")}
            </Button>
          </div>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table data-testid="tasks-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("tasks.status")}</TableHead>
              <TableHead>{t("tasks.target")}</TableHead>
              <TableHead>{t("tasks.buildArtifact")}</TableHead>
              <TableHead>{t("tasks.artifactType")}</TableHead>
              <TableHead>{t("tasks.strategy")}</TableHead>
              <TableHead>{t("tasks.executions")}</TableHead>
              <TableHead>{t("tasks.createdAt")}</TableHead>
              <TableHead>{t("tasks.startedAt")}</TableHead>
              <TableHead>{t("tasks.finishedAt")}</TableHead>
              <TableHead>{t("tasks.id")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tasks.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={10}
                  className="text-muted-foreground text-center"
                >
                  {loading ? "…" : t("tasks.empty")}
                </TableCell>
              </TableRow>
            ) : (
              tasks.map((task) => (
                <TableRow key={task.id}>
                  <TableCell>
                    <ToneBadge tone={STATUS_TONE[task.status]}>
                      {task.status}
                    </ToneBadge>
                  </TableCell>
                  <TableCell>{task.target}</TableCell>
                  <TableCell data-testid={`task-build-artifact-${task.id}`}>
                    {task.build_artifact
                      ? buildArtifactText(task.build_artifact)
                      : "-"}
                  </TableCell>
                  <TableCell>{task.artifact_type}</TableCell>
                  <TableCell>{task.node_strategy}</TableCell>
                  <TableCell>{task.execution_count}</TableCell>
                  <TableCell>{formatDateTime(task.created_at)}</TableCell>
                  <TableCell>{formatDateTime(task.started_at)}</TableCell>
                  <TableCell>{formatDateTime(task.finished_at)}</TableCell>
                  <TableCell>
                    <Link
                      href={`/tasks/detail?id=${task.id}`}
                      data-testid={`task-view-${task.id}`}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {t("tasks.view")}
                    </Link>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>

        <div className="mt-3 flex items-center justify-end gap-4">
          <span className="text-muted-foreground text-sm">
            {t("tasks.total")}: {total}
          </span>
          <Select value={String(pageSize)} onValueChange={onSizeChange}>
            <SelectTrigger size="sm" className="w-28" data-testid="tasks-page-size">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {TASK_PAGE_SIZES.map((size) => (
                  <SelectItem key={size} value={String(size)}>
                    {size} / {t("tasks.pageSize")}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Pagination className="mx-0 w-auto">
            <PaginationContent>
              <PaginationItem>
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="tasks-prev"
                  disabled={page <= 1 || loading}
                  onClick={() =>
                    load(page - 1, pageSize, buildFilter, statusFilter)
                  }
                >
                  ‹
                </Button>
              </PaginationItem>
              <PaginationItem>
                <span className="px-2 text-sm" data-testid="tasks-page-indicator">
                  {page} / {totalPages}
                </span>
              </PaginationItem>
              <PaginationItem>
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="tasks-next"
                  disabled={page >= totalPages || loading}
                  onClick={() =>
                    load(page + 1, pageSize, buildFilter, statusFilter)
                  }
                >
                  ›
                </Button>
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        </div>
      </CardContent>
    </Card>
  );
}
