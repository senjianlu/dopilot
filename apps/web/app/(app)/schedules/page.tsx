"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
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
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertTitle } from "@/components/ui/alert";
import {
  NODE_BADGE_TONE,
  ToneBadge,
} from "@/components/features/status-badge";
import { ArchivedIndicator } from "@/components/features/archived-indicator";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { matchesPrefix } from "@/lib/search";
import {
  createSchedule,
  deleteSchedule,
  disableAllSchedules,
  listSchedules,
  previewNextRun,
  triggerSchedule,
  updateSchedule,
} from "@/lib/api/schedules";
import { listTemplates } from "@/lib/api/templates";
import { listNodes } from "@/lib/api/nodes";
import type {
  ApiError,
  ExecutionTemplate,
  NodeInfo,
  NodeStrategy,
  Schedule,
  ScheduleOverrides,
  TriggerType,
} from "@/lib/api/types";
import { nodeBadge } from "@/lib/nodeBadge";
import { nodeKey, selectableNodes as selectableNodesOf } from "@/lib/nodeSelection";
import { checkScrapyCommand } from "@/lib/scrapyCommand";
import { formatDateTime } from "@/lib/format";
import { useConfirm } from "@/hooks/use-confirm";

// shadcn/Radix Select cannot bind an empty-string value, so "none" is the
// sentinel for "no node-strategy override".
type OverrideStrategy = "none" | NodeStrategy;

// Log-flood guard / auto-disable: consecutive erroneous runs recorded in the
// auto-disable reason (falls back to the live derived counter).
function autoDisabledCount(schedule: Schedule): number {
  const reason = schedule.auto_disabled_reason ?? {};
  const n = reason.consecutive_errors;
  return typeof n === "number" ? n : schedule.consecutive_error_count;
}

export default function SchedulesPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const confirm = useConfirm();

  const [schedules, setSchedules] = React.useState<Schedule[]>([]);
  // Global enabled count from the server (the list truncates at 200 rows, so
  // deriving this from `schedules` would wrongly disable the button).
  const [enabledTotal, setEnabledTotal] = React.useState(0);
  const [disablingAll, setDisablingAll] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [templates, setTemplates] = React.useState<ExecutionTemplate[]>([]);
  const [nodes, setNodes] = React.useState<NodeInfo[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [triggeringId, setTriggeringId] = React.useState("");
  // The row whose enable/disable toggle is in flight; blocks duplicate submits.
  const [togglingId, setTogglingId] = React.useState("");
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState("");
  const [estimatedNextRun, setEstimatedNextRun] = React.useState("");

  const [name, setName] = React.useState("");
  const [enabled, setEnabled] = React.useState(false);
  // Concurrency gate (decision 0022). 0 means unlimited and MUST survive the
  // round trip: `Number(v) || 1` and friends would silently turn it into 1 and
  // make the escape hatch unreachable from the only admin UI there is.
  const [maxConcurrency, setMaxConcurrency] = React.useState(1);
  const [templateId, setTemplateId] = React.useState("");
  const [triggerType, setTriggerType] = React.useState<TriggerType>("interval");
  const [intervalSeconds, setIntervalSeconds] = React.useState(60);
  const [cron, setCron] = React.useState("");
  const [overrideCommand, setOverrideCommand] = React.useState("");
  const [overrideStrategy, setOverrideStrategy] =
    React.useState<OverrideStrategy>("none");
  const [overrideNodeIds, setOverrideNodeIds] = React.useState<string[]>([]);

  const selectableNodes = React.useMemo(
    () => selectableNodesOf(nodes),
    [nodes],
  );
  const overrideSelectedStrategy = overrideStrategy === "selected";

  const overrideCommandCheck = checkScrapyCommand(overrideCommand);
  const overrideCommandError =
    overrideCommand && !overrideCommandCheck.valid
      ? t(
          `commandErrors.${overrideCommandCheck.reason}`,
          t("commandErrors.invalid"),
        )
      : "";

  // Client-side prefix search over the loaded schedules (see lib/search).
  const visibleSchedules = React.useMemo(
    () => schedules.filter((sch) => matchesPrefix(sch.name, search)),
    [schedules, search],
  );

  function templateName(id: string): string {
    return templates.find((tpl) => tpl.id === id)?.name ?? id;
  }

  // Resolve archive state from the already-loaded templates list (no extra API
  // call, no ScheduleView change). A schedule whose template is missing/stale
  // simply shows no indicator.
  function templateArchived(id: string): boolean {
    return (
      templates.find((tpl) => tpl.id === id)?.build_artifact_archived ?? false
    );
  }

  function triggerTimeText(schedule: Schedule): string {
    if (schedule.trigger_type === "cron") return schedule.cron ?? "-";
    return t("schedules.everySeconds", {
      seconds: schedule.interval_seconds ?? 0,
    });
  }

  const updateEstimate = React.useCallback(
    async (type: TriggerType, seconds: number, cronExpr: string) => {
      if (type === "interval") {
        setEstimatedNextRun(
          seconds > 0
            ? formatDateTime(new Date(Date.now() + seconds * 1000).toISOString())
            : "",
        );
        return;
      }
      if (!cronExpr.trim()) {
        setEstimatedNextRun("");
        return;
      }
      try {
        const res = await previewNextRun({ trigger_type: "cron", cron: cronExpr });
        setEstimatedNextRun(
          res.next_run_at
            ? formatDateTime(res.next_run_at)
            : t("schedules.nextRunPending"),
        );
      } catch {
        setEstimatedNextRun(t("schedules.nextRunPending"));
      }
    },
    [t],
  );

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [sch, tpls, nds] = await Promise.all([
        listSchedules(),
        listTemplates(),
        listNodes(),
      ]);
      setSchedules(sch.schedules);
      setEnabledTotal(sch.enabled_total);
      setTemplates(tpls);
      setNodes(nds);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditingId("");
    setName("");
    // Match the backend: a new schedule is created disabled by default.
    setEnabled(false);
    setMaxConcurrency(1);
    setTemplateId(templates[0]?.id ?? "");
    setTriggerType("interval");
    setIntervalSeconds(60);
    setCron("");
    setOverrideCommand("");
    setOverrideStrategy("none");
    setOverrideNodeIds([]);
    setCreateError("");
    setDialogOpen(true);
    void updateEstimate("interval", 60, "");
  }

  function openEdit(schedule: Schedule) {
    const ov = schedule.overrides ?? {};
    const ovCommand = typeof ov.command === "string" ? ov.command : "";
    const ovStrategy = (ov.node_strategy as OverrideStrategy) ?? "none";
    const ovNodeIds = Array.isArray(ov.node_ids)
      ? (ov.node_ids as string[])
      : [];
    const seconds = schedule.interval_seconds ?? 60;
    const cronExpr = schedule.cron ?? "";
    setEditingId(schedule.id);
    setName(schedule.name);
    setEnabled(schedule.enabled);
    setMaxConcurrency(schedule.max_concurrency ?? 1);
    setTemplateId(schedule.execution_template_id);
    setTriggerType(schedule.trigger_type);
    setIntervalSeconds(seconds);
    setCron(cronExpr);
    setOverrideCommand(ovCommand);
    // Absent strategy override falls back to the "none" sentinel.
    setOverrideStrategy(ovStrategy);
    setOverrideNodeIds(ovStrategy === "selected" ? ovNodeIds : []);
    setCreateError("");
    setDialogOpen(true);
    void updateEstimate(schedule.trigger_type, seconds, cronExpr);
  }

  function toggleOverrideNode(key: string) {
    setOverrideNodeIds((ids) =>
      ids.includes(key) ? ids.filter((id) => id !== key) : [...ids, key],
    );
  }

  function buildOverrides(): ScheduleOverrides | undefined {
    const overrides: ScheduleOverrides = {};
    if (overrideCommand.trim()) {
      overrides.command = overrideCommand.trim();
    }
    if (overrideStrategy !== "none") {
      overrides.node_strategy = overrideStrategy;
      if (overrideSelectedStrategy) {
        overrides.node_ids = overrideNodeIds;
      }
    }
    return Object.keys(overrides).length ? overrides : undefined;
  }

  const canSubmit = !overrideCommand || overrideCommandCheck.valid;

  async function submitDialog() {
    if (overrideCommand && !overrideCommandCheck.valid) {
      setCreateError(t("schedules.invalidCommand"));
      return;
    }
    setCreating(true);
    setCreateError("");
    const payload = {
      name,
      enabled,
      max_concurrency: maxConcurrency,
      execution_template_id: templateId,
      trigger_type: triggerType,
      interval_seconds: triggerType === "interval" ? intervalSeconds : null,
      cron: triggerType === "cron" ? cron : null,
      overrides: buildOverrides(),
    };
    try {
      if (editingId) {
        await updateSchedule(editingId, payload);
      } else {
        await createSchedule(payload);
      }
      setDialogOpen(false);
      await load();
    } catch {
      setCreateError(t("schedules.createError"));
    } finally {
      setCreating(false);
    }
  }

  // Quick enable/disable from the table: send only { enabled } and reload on
  // success. A pending row id blocks duplicate submits; no optimistic UI.
  async function onToggleEnabled(schedule: Schedule, next: boolean) {
    if (togglingId) return;
    setTogglingId(schedule.id);
    try {
      await updateSchedule(schedule.id, { enabled: next });
      await load();
    } finally {
      setTogglingId("");
    }
  }

  async function onTrigger(schedule: Schedule) {
    setTriggeringId(schedule.id);
    try {
      const res = await triggerSchedule(schedule.id);
      router.push(`/tasks/detail?id=${res.task_id}`);
    } catch (error) {
      // A 409 means the concurrency gate refused: nothing was created, so stay
      // on this page and say why. Without this the rejection was unhandled.
      const envelope = (error as { response?: { data?: ApiError } })?.response
        ?.data;
      if (envelope?.code === "schedule.concurrency_limit") {
        const detail = (envelope.detail ?? {}) as {
          active?: number;
          limit?: number;
        };
        toast.error(
          t("schedules.concurrencyLimitHit", {
            active: detail.active ?? 0,
            limit: detail.limit ?? 0,
          }),
        );
      } else {
        toast.error(t("schedules.triggerError"));
      }
    } finally {
      setTriggeringId("");
    }
  }

  // Pre-upgrade brake: disable every enabled schedule in one confirmed shot.
  async function onDisableAll() {
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("schedules.confirmDisableAll", { count: enabledTotal }),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    setDisablingAll(true);
    try {
      await disableAllSchedules();
      await load();
    } finally {
      setDisablingAll(false);
    }
  }

  async function onDelete(schedule: Schedule) {
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("schedules.confirmDelete", { name: schedule.name }),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    await deleteSchedule(schedule.id);
    await load();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("schedules.title")}</CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            <Input
              data-testid="schedule-search"
              className="h-9 w-48"
              placeholder={t("schedules.search")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button data-testid="schedule-create" onClick={openCreate}>
              {t("schedules.create")}
            </Button>
            <Button
              variant="outline"
              className="text-destructive"
              data-testid="schedule-disable-all"
              disabled={enabledTotal === 0 || disablingAll}
              onClick={onDisableAll}
            >
              {disablingAll && <Spinner data-icon="inline-start" />}
              {t("schedules.disableAll")}
            </Button>
            <Button variant="outline" onClick={load}>
              {t("schedules.refresh")}
            </Button>
          </div>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table data-testid="schedules-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("schedules.name")}</TableHead>
              <TableHead>{t("schedules.enabled")}</TableHead>
              <TableHead>{t("schedules.maxConcurrency")}</TableHead>
              <TableHead>{t("schedules.template")}</TableHead>
              <TableHead>{t("schedules.triggerType")}</TableHead>
              <TableHead>{t("schedules.triggerTime")}</TableHead>
              <TableHead>{t("schedules.nextRun")}</TableHead>
              <TableHead className="text-right">
                {t("schedules.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visibleSchedules.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="text-muted-foreground text-center"
                >
                  {loading ? "…" : t("schedules.empty")}
                </TableCell>
              </TableRow>
            ) : (
              visibleSchedules.map((schedule) => (
                <TableRow key={schedule.id}>
                  <TableCell data-testid={`schedule-name-${schedule.name}`}>
                    <span className="inline-flex items-center gap-2">
                      {schedule.name}
                      {schedule.auto_disabled_at ? (
                        <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            {/* a focusable trigger: keyboard users reach the
                                reason via Tab + focus, not just hover */}
                            <Badge asChild variant="destructive">
                              <button
                                type="button"
                                data-testid={`schedule-auto-disabled-${schedule.name}`}
                              >
                                {t("schedules.autoDisabled")}
                              </button>
                            </Badge>
                          </TooltipTrigger>
                          <TooltipContent>
                            {t("schedules.autoDisabledHint", {
                              count: autoDisabledCount(schedule),
                              at: formatDateTime(schedule.auto_disabled_at),
                            })}
                          </TooltipContent>
                        </Tooltip>
                        </TooltipProvider>
                      ) : null}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Switch
                      size="sm"
                      checked={schedule.enabled}
                      disabled={togglingId === schedule.id}
                      data-testid={`schedule-enabled-${schedule.name}`}
                      aria-label={t("schedules.enabled")}
                      onCheckedChange={(next) =>
                        onToggleEnabled(schedule, next)
                      }
                    />
                  </TableCell>
                  <TableCell data-testid={`schedule-concurrency-${schedule.name}`}>
                    {schedule.max_concurrency === 0
                      ? t("schedules.unlimited")
                      : schedule.max_concurrency}
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1">
                      {templateName(schedule.execution_template_id)}
                      {templateArchived(schedule.execution_template_id) && (
                        <ArchivedIndicator />
                      )}
                    </span>
                  </TableCell>
                  <TableCell>{schedule.trigger_type}</TableCell>
                  <TableCell>{triggerTimeText(schedule)}</TableCell>
                  <TableCell>{formatDateTime(schedule.next_run_at)}</TableCell>
                  <TableCell className="text-right">
                    {/* Drill-down into this schedule's task history. The id
                        drives the filter; the name only labels the chip. */}
                    <Button
                      variant="ghost"
                      size="sm"
                      asChild
                      data-testid={`schedule-tasks-${schedule.name}`}
                    >
                      <Link
                        href={
                          `/tasks?schedule_id=${encodeURIComponent(schedule.id)}` +
                          `&schedule_name=${encodeURIComponent(schedule.name)}`
                        }
                      >
                        {t("schedules.viewTasks")}
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`schedule-trigger-${schedule.name}`}
                      disabled={triggeringId === schedule.id}
                      onClick={() => onTrigger(schedule)}
                    >
                      {triggeringId === schedule.id && (
                        <Spinner data-icon="inline-start" />
                      )}
                      {t("schedules.triggerNow")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`schedule-edit-${schedule.name}`}
                      onClick={() => openEdit(schedule)}
                    >
                      {t("schedules.edit")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive"
                      onClick={() => onDelete(schedule)}
                    >
                      {t("schedules.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="schedule-dialog" className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editingId ? t("schedules.editTitle") : t("schedules.createTitle")}
            </DialogTitle>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="sch-name">{t("schedules.name")}</FieldLabel>
              <Input
                id="sch-name"
                data-testid="schedule-name-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field orientation="horizontal">
              <Switch
                id="sch-enabled"
                checked={enabled}
                data-testid="schedule-enabled-input"
                onCheckedChange={setEnabled}
              />
              <FieldLabel htmlFor="sch-enabled">
                {t("schedules.enabled")}
              </FieldLabel>
            </Field>
            <Field>
              <FieldLabel htmlFor="sch-max-concurrency">
                {t("schedules.maxConcurrency")}
              </FieldLabel>
              <Input
                id="sch-max-concurrency"
                type="number"
                min={0}
                max={2147483647}
                value={maxConcurrency}
                data-testid="schedule-max-concurrency-input"
                onChange={(e) => {
                  // Parse explicitly: `Number(v) || 1` would turn the meaningful
                  // 0 ("unlimited") into 1. An empty/!isInteger box falls back
                  // to the default instead of submitting NaN.
                  const parsed = Number(e.target.value);
                  setMaxConcurrency(Number.isInteger(parsed) ? parsed : 1);
                }}
              />
              <FieldDescription>
                {t("schedules.maxConcurrencyHint")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel>{t("schedules.template")}</FieldLabel>
              <Select value={templateId} onValueChange={setTemplateId}>
                <SelectTrigger
                  className="w-full"
                  data-testid="schedule-template-select"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {templates.map((tpl) => (
                      <SelectItem key={tpl.id} value={tpl.id}>
                        {tpl.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>{t("schedules.triggerType")}</FieldLabel>
              <Select
                value={triggerType}
                onValueChange={(v) => {
                  const next = v as TriggerType;
                  setTriggerType(next);
                  void updateEstimate(next, intervalSeconds, cron);
                }}
              >
                <SelectTrigger className="w-full" data-testid="schedule-trigger-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="interval">
                      {t("schedules.intervalType")}
                    </SelectItem>
                    <SelectItem value="cron">
                      {t("schedules.cronType")}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            {triggerType === "interval" ? (
              <Field>
                <FieldLabel htmlFor="sch-interval">
                  {t("schedules.interval")}
                </FieldLabel>
                <Input
                  id="sch-interval"
                  type="number"
                  min={1}
                  data-testid="schedule-interval"
                  value={intervalSeconds}
                  onChange={(e) => {
                    const v = Number(e.target.value) || 0;
                    setIntervalSeconds(v);
                    void updateEstimate("interval", v, cron);
                  }}
                />
              </Field>
            ) : (
              <Field>
                <FieldLabel htmlFor="sch-cron">{t("schedules.cron")}</FieldLabel>
                <Input
                  id="sch-cron"
                  data-testid="schedule-cron"
                  placeholder={t("schedules.cronPlaceholder")}
                  value={cron}
                  onChange={(e) => {
                    setCron(e.target.value);
                    void updateEstimate("cron", intervalSeconds, e.target.value);
                  }}
                />
              </Field>
            )}
            <Field data-invalid={!!overrideCommandError || undefined}>
              <FieldLabel htmlFor="sch-command">
                {t("schedules.overrideCommand")}
              </FieldLabel>
              <Input
                id="sch-command"
                data-testid="schedule-command-input"
                aria-invalid={!!overrideCommandError || undefined}
                placeholder={t("schedules.overrideCommandNone")}
                value={overrideCommand}
                onChange={(e) => setOverrideCommand(e.target.value)}
              />
              {overrideCommandError && (
                <FieldError data-testid="schedule-command-error">
                  {overrideCommandError}
                </FieldError>
              )}
            </Field>
            <Field>
              <FieldLabel>{t("schedules.overrideStrategy")}</FieldLabel>
              <Select
                value={overrideStrategy}
                onValueChange={(v) => setOverrideStrategy(v as OverrideStrategy)}
              >
                <SelectTrigger className="w-full" data-testid="schedule-override-strategy">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="none">
                      {t("schedules.overrideStrategyNone")}
                    </SelectItem>
                    <SelectItem value="all">all</SelectItem>
                    <SelectItem value="random">random</SelectItem>
                    <SelectItem value="selected">selected</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            {overrideSelectedStrategy && (
              <Field>
                <FieldLabel>{t("schedules.overrideNodes")}</FieldLabel>
                <div
                  className="flex flex-wrap gap-2"
                  data-testid="schedule-node-picker"
                >
                  {selectableNodes.map((n) => {
                    const key = nodeKey(n);
                    const active = overrideNodeIds.includes(key);
                    return (
                      <button
                        type="button"
                        key={key}
                        onClick={() => toggleOverrideNode(key)}
                        aria-pressed={active}
                        data-testid={`schedule-node-${n.agent_id}`}
                      >
                        <ToneBadge
                          tone={active ? NODE_BADGE_TONE[nodeBadge(n)] : "gray"}
                          className={active ? "" : "opacity-60"}
                        >
                          {n.agent_id ?? n.endpoint}
                        </ToneBadge>
                      </button>
                    );
                  })}
                </div>
              </Field>
            )}
            <Field>
              <FieldLabel>{t("schedules.estimatedNextRun")}</FieldLabel>
              <span
                className="text-muted-foreground text-sm"
                data-testid="schedule-next-run"
              >
                {estimatedNextRun || "-"}
              </span>
            </Field>
            {createError && (
              <Alert variant="destructive">
                <AlertTitle>{createError}</AlertTitle>
              </Alert>
            )}
          </FieldGroup>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t("schedules.cancel")}
            </Button>
            <Button
              data-testid="schedule-submit"
              disabled={!canSubmit || creating}
              onClick={submitDialog}
            >
              {creating && <Spinner data-icon="inline-start" />}
              {editingId ? t("schedules.save") : t("schedules.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
