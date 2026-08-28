"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { X } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

// Mirrors MAX_TARGET_QUERY_LEN in apps/server/dopilot_server/api/v1/tasks.py.
// Capping the input means the UI can never build a request the backend would
// reject; the server-side check stays as the defence for direct API callers.
const MAX_TARGET_QUERY_LEN = 100;

// How long typing settles before the search term is committed to the filters.
const SEARCH_DEBOUNCE_MS = 300;

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

// Every filter lives in ONE object so that a debounced update can never ship a
// stale partial snapshot: callers always merge through setFilters(prev => ...),
// and a single effect turns the current object into the request.
interface TaskFilters {
  page: number;
  pageSize: TaskPageSize;
  build: string; // BUILD_ALL or a build_artifact_id
  status: string; // STATUS_ALL or a concrete task status
  scheduleId: string | null; // read from the URL on mount only
  q: string; // the committed (post-debounce) search term
}

function TasksPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();

  // The schedules page links here as /tasks?schedule_id=...&schedule_name=...
  // The id drives the query; the name is display-only chip text and is never
  // sent back to the API, so a tampered value can at worst mislabel the chip.
  const initialScheduleId = searchParams.get("schedule_id");
  const scheduleLabel = searchParams.get("schedule_name") ?? initialScheduleId;

  const [filters, setFilters] = React.useState<TaskFilters>(() => ({
    page: 1,
    // Computed in the initializer rather than in a mount effect, so the first
    // render already requests the right page size (no throwaway request).
    pageSize: pickPageSizeFromHeight(),
    build: BUILD_ALL,
    status: STATUS_ALL,
    scheduleId: initialScheduleId,
    q: "",
  }));
  const [searchInput, setSearchInput] = React.useState("");
  const [reloadNonce, setReloadNonce] = React.useState(0);

  const [tasks, setTasks] = React.useState<TaskSummary[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [total, setTotal] = React.useState(0);
  const [builds, setBuilds] = React.useState<BuildArtifactOption[]>([]);

  // Monotonic request id: effects fire in order but responses do not arrive in
  // order, so a slow earlier request must not overwrite a newer result.
  const reqSeq = React.useRef(0);

  // Debounce commits the typed value INTO the filters; it never issues the
  // request itself. That is what keeps a pending timer from resurrecting the
  // dropdown/chip values that were current when the keystroke happened.
  React.useEffect(() => {
    if (searchInput === filters.q) return;
    const timer = setTimeout(() => {
      setFilters((prev) => ({ ...prev, q: searchInput, page: 1 }));
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput, filters.q]);

  // The one and only place a request is made. It reads the whole current
  // filter object, so a request is never assembled from mixed-age values.
  React.useEffect(() => {
    const seq = ++reqSeq.current;
    let alive = true;
    setLoading(true);
    listTasks({
      page: filters.page,
      pageSize: filters.pageSize,
      buildArtifactId: filters.build === BUILD_ALL ? null : filters.build,
      status:
        filters.status === STATUS_ALL ? null : (filters.status as TaskStatus),
      scheduleId: filters.scheduleId,
      q: filters.q || null,
    })
      .then((res) => {
        if (!alive || seq !== reqSeq.current) return;
        setTasks(res.tasks);
        setTotal(res.total);
        setBuilds(res.build_artifacts);
      })
      .catch(() => {
        if (!alive || seq !== reqSeq.current) return;
        toast.error(t("tasks.loadFailed"));
      })
      .finally(() => {
        if (alive && seq === reqSeq.current) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [filters, reloadNonce, t]);

  const totalPages = Math.max(1, Math.ceil(total / filters.pageSize));

  // Changing a filter resets to page 1; paging/size keep every other filter,
  // which falls out of merging into the previous object instead of rebuilding.
  function onBuildChange(value: string) {
    setFilters((prev) => ({ ...prev, build: value, page: 1 }));
  }

  function onStatusChange(value: string) {
    setFilters((prev) => ({ ...prev, status: value, page: 1 }));
  }

  function onSizeChange(value: string) {
    const size = Number(value) as TaskPageSize;
    setFilters((prev) => ({ ...prev, pageSize: size, page: 1 }));
  }

  function goToPage(page: number) {
    setFilters((prev) => ({ ...prev, page }));
  }

  function onSearchKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    // Commit immediately. The debounce effect's guard (searchInput === q) then
    // short-circuits, and its cleanup already cleared the pending timer, so
    // this cannot be followed by a second shot 300ms later.
    setFilters((prev) => ({ ...prev, q: searchInput, page: 1 }));
  }

  function clearScheduleFilter() {
    setFilters((prev) => ({ ...prev, scheduleId: null, page: 1 }));
    // Drop the query string too, otherwise a reload would bring the filter back.
    router.replace("/tasks");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tasks.title")}</CardTitle>
        <CardAction>
          <div className="flex flex-wrap items-center gap-2">
            {filters.scheduleId && (
              <Badge
                variant="secondary"
                className="gap-1"
                data-testid="tasks-schedule-filter"
              >
                {t("tasks.scheduleFilter")}: {scheduleLabel}
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={t("tasks.clearFilter")}
                  data-testid="tasks-schedule-filter-clear"
                  onClick={clearScheduleFilter}
                  className="-mr-1"
                >
                  {/* icon-xs already sizes the svg; no explicit size class. */}
                  <X />
                </Button>
              </Badge>
            )}
            <Input
              className="w-48"
              value={searchInput}
              maxLength={MAX_TARGET_QUERY_LEN}
              placeholder={t("tasks.searchTarget")}
              aria-label={t("tasks.searchTarget")}
              data-testid="tasks-target-search"
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={onSearchKeyDown}
            />
            <Select value={filters.status} onValueChange={onStatusChange}>
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
            <Select value={filters.build} onValueChange={onBuildChange}>
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
            <Button onClick={() => setReloadNonce((n) => n + 1)}>
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
          <Select
            value={String(filters.pageSize)}
            onValueChange={onSizeChange}
          >
            <SelectTrigger
              size="sm"
              className="w-28"
              data-testid="tasks-page-size"
            >
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
                  disabled={filters.page <= 1 || loading}
                  onClick={() => goToPage(filters.page - 1)}
                >
                  ‹
                </Button>
              </PaginationItem>
              <PaginationItem>
                <span
                  className="px-2 text-sm"
                  data-testid="tasks-page-indicator"
                >
                  {filters.page} / {totalPages}
                </span>
              </PaginationItem>
              <PaginationItem>
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="tasks-next"
                  disabled={filters.page >= totalPages || loading}
                  onClick={() => goToPage(filters.page + 1)}
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

export default function TasksPage() {
  // Static export prerenders this route; useSearchParams must sit under Suspense.
  return (
    <React.Suspense fallback={<div data-testid="tasks-table" />}>
      <TasksPageInner />
    </React.Suspense>
  );
}
