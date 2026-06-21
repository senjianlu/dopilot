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
import {
  TASK_PAGE_SIZES,
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

// "All spiders" sentinel (Radix Select forbids an empty-string value).
const SPIDER_ALL = "__all__";

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
  const [spiders, setSpiders] = React.useState<string[]>([]);
  const [spider, setSpider] = React.useState(SPIDER_ALL);

  const load = React.useCallback(
    async (nextPage: number, size: TaskPageSize, spiderFilter: string) => {
      setLoading(true);
      try {
        const res = await listTasks({
          page: nextPage,
          pageSize: size,
          spider: spiderFilter === SPIDER_ALL ? null : spiderFilter,
        });
        setTasks(res.tasks);
        setTotal(res.total);
        setPage(res.page);
        setPageSize(res.page_size as TaskPageSize);
        setSpiders(res.spiders);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  React.useEffect(() => {
    const size = pickPageSizeFromHeight();
    setPageSize(size);
    void load(1, size, SPIDER_ALL);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  function onSpiderChange(value: string) {
    setSpider(value);
    void load(1, pageSize, value);
  }

  function onSizeChange(value: string) {
    const size = Number(value) as TaskPageSize;
    void load(1, size, spider);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tasks.title")}</CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            <Select value={spider} onValueChange={onSpiderChange}>
              <SelectTrigger
                className="min-w-40"
                data-testid="tasks-spider-filter"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={SPIDER_ALL}>
                    {t("tasks.spiderAll")}
                  </SelectItem>
                  {spiders.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button onClick={() => load(page, pageSize, spider)}>
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
              <TableHead>{t("tasks.spider")}</TableHead>
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
                  <TableCell>{task.spider ?? "-"}</TableCell>
                  <TableCell>{task.artifact_type}</TableCell>
                  <TableCell>{task.node_strategy}</TableCell>
                  <TableCell>{task.execution_count}</TableCell>
                  <TableCell>{task.created_at ?? "-"}</TableCell>
                  <TableCell>{task.started_at ?? "-"}</TableCell>
                  <TableCell>{task.finished_at ?? "-"}</TableCell>
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
                  onClick={() => load(page - 1, pageSize, spider)}
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
                  onClick={() => load(page + 1, pageSize, spider)}
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
