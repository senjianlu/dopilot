"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
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
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
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
import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  previewNextRun,
  triggerSchedule,
  updateSchedule,
} from "@/lib/api/schedules";
import { listTemplates } from "@/lib/api/templates";
import { listNodes } from "@/lib/api/nodes";
import type {
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

export default function SchedulesPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const confirm = useConfirm();

  const [schedules, setSchedules] = React.useState<Schedule[]>([]);
  const [templates, setTemplates] = React.useState<ExecutionTemplate[]>([]);
  const [nodes, setNodes] = React.useState<NodeInfo[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [triggeringId, setTriggeringId] = React.useState("");
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState("");
  const [estimatedNextRun, setEstimatedNextRun] = React.useState("");

  const [name, setName] = React.useState("");
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

  function templateName(id: string): string {
    return templates.find((tpl) => tpl.id === id)?.name ?? id;
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
      setSchedules(sch);
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

  async function onTrigger(schedule: Schedule) {
    setTriggeringId(schedule.id);
    try {
      const res = await triggerSchedule(schedule.id);
      router.push(`/tasks/detail?id=${res.task_id}`);
    } finally {
      setTriggeringId("");
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
            <Button data-testid="schedule-create" onClick={openCreate}>
              {t("schedules.create")}
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
            {schedules.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-muted-foreground text-center"
                >
                  {loading ? "…" : t("schedules.empty")}
                </TableCell>
              </TableRow>
            ) : (
              schedules.map((schedule) => (
                <TableRow key={schedule.id}>
                  <TableCell data-testid={`schedule-name-${schedule.name}`}>
                    {schedule.name}
                  </TableCell>
                  <TableCell>
                    {templateName(schedule.execution_template_id)}
                  </TableCell>
                  <TableCell>{schedule.trigger_type}</TableCell>
                  <TableCell>{triggerTimeText(schedule)}</TableCell>
                  <TableCell>{formatDateTime(schedule.next_run_at)}</TableCell>
                  <TableCell className="text-right">
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
