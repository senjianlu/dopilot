"use client";

import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToneBadge, type Tone } from "@/components/features/status-badge";
import {
  getResourceStats,
  rewriteAof,
  sweepNow,
  terminalCleanup,
} from "@/lib/api/maintenance";
import type {
  ResourceLevel,
  ResourceScopeStatus,
  ResourceStatEntry,
  ResourceStatScope,
  ResourceStatsResponse,
  SweepNowResponse,
  TerminalCleanupResponse,
} from "@/lib/api/types";
import { formatBytes, formatDateTime } from "@/lib/format";
import { useConfirm } from "@/hooks/use-confirm";

const POLL_MS = 10_000;

const LEVEL_TONE: Record<ResourceLevel, Tone> = {
  ok: "green",
  warn: "amber",
  critical: "red",
  unknown: "gray",
};

const STATUS_TONE: Record<ResourceScopeStatus, Tone> = {
  ok: "green",
  stale: "amber",
  unavailable: "gray",
};

type TFn = ReturnType<typeof useTranslation>["t"];

function metricLabel(t: TFn, key: string): string {
  const idx = key.indexOf(":");
  const base = idx === -1 ? key : key.slice(0, idx);
  const suffix = idx === -1 ? "" : key.slice(idx + 1);
  const label = t(`maintenance.metrics.${base}`, { defaultValue: base });
  return suffix ? `${label} · ${suffix}` : label;
}

function formatAge(t: TFn, seconds: number): string {
  if (seconds >= 86400) {
    return t("maintenance.ageDays", { n: Math.floor(seconds / 86400) });
  }
  return t("maintenance.ageSeconds", { n: seconds });
}

function formatValue(t: TFn, entry: ResourceStatEntry): string {
  if (entry.value === null) return t("maintenance.unlimited");
  if (entry.kind === "bytes") return formatBytes(entry.value);
  if (entry.kind === "age") return formatAge(t, entry.value);
  return entry.value.toLocaleString();
}

function formatLimit(t: TFn, entry: ResourceStatEntry): string {
  if (entry.limit === null) return t("maintenance.unlimited");
  if (entry.kind === "bytes") return formatBytes(entry.limit);
  if (entry.kind === "age") return formatAge(t, entry.limit);
  return entry.limit.toLocaleString();
}

function usagePercent(entry: ResourceStatEntry): number | null {
  if (entry.value === null || entry.limit === null || entry.limit <= 0) {
    return null;
  }
  return Math.min(100, (entry.value / entry.limit) * 100);
}

function scopeTitle(t: TFn, scope: string): string {
  if (scope === "server") return t("maintenance.scopeServer");
  if (scope === "postgres") return t("maintenance.scopePostgres");
  if (scope === "redis") return t("maintenance.scopeRedis");
  if (scope.startsWith("agent:")) {
    return t("maintenance.scopeAgent", { id: scope.slice("agent:".length) });
  }
  return scope;
}

function MetricRow({ entry }: { entry: ResourceStatEntry }) {
  const { t } = useTranslation();
  const pct = usagePercent(entry);
  return (
    <TableRow data-testid={`resource-entry-${entry.key}`}>
      <TableCell>{metricLabel(t, entry.key)}</TableCell>
      <TableCell className="tabular-nums">{formatValue(t, entry)}</TableCell>
      <TableCell className="tabular-nums text-muted-foreground">
        {formatLimit(t, entry)}
      </TableCell>
      <TableCell className="w-32">
        {pct !== null && <Progress value={pct} />}
      </TableCell>
      <TableCell className="text-right">
        <ToneBadge
          tone={LEVEL_TONE[entry.level]}
          data-testid={`resource-level-${entry.key}`}
        >
          {entry.level}
        </ToneBadge>
      </TableCell>
    </TableRow>
  );
}

function ScopeCard({ scope }: { scope: ResourceStatScope }) {
  const { t } = useTranslation();
  const unavailable = scope.status === "unavailable";
  return (
    <Card data-testid={`resource-scope-${scope.scope}`}>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">
            {scopeTitle(t, scope.scope)}
          </CardTitle>
          {scope.status !== "ok" && (
            <ToneBadge
              tone={STATUS_TONE[scope.status]}
              data-testid={`resource-scope-status-${scope.scope}`}
            >
              {t(
                unavailable
                  ? "maintenance.statusUnavailable"
                  : "maintenance.statusStale",
              )}
            </ToneBadge>
          )}
        </div>
        {scope.status === "stale" && scope.sampled_at && (
          <CardDescription data-testid={`resource-scope-sampled-${scope.scope}`}>
            {t("maintenance.sampledAt", {
              time: formatDateTime(scope.sampled_at),
            })}
          </CardDescription>
        )}
        {unavailable && scope.last_seen_at && (
          <CardDescription data-testid={`resource-scope-lastseen-${scope.scope}`}>
            {t("maintenance.lastSeen", {
              time: formatDateTime(scope.last_seen_at),
            })}
          </CardDescription>
        )}
      </CardHeader>
      {!unavailable && scope.entries.length > 0 && (
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("maintenance.colMetric")}</TableHead>
                <TableHead>{t("maintenance.colCurrent")}</TableHead>
                <TableHead>{t("maintenance.colLimit")}</TableHead>
                <TableHead />
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {scope.entries.map((entry) => (
                <MetricRow key={entry.key} entry={entry} />
              ))}
            </TableBody>
          </Table>
        </CardContent>
      )}
    </Card>
  );
}

export default function MaintenancePage() {
  const { t } = useTranslation();
  const confirm = useConfirm();

  const [stats, setStats] = React.useState<ResourceStatsResponse | null>(null);
  const [loadError, setLoadError] = React.useState(false);

  // cleanup form
  const [olderThanDays, setOlderThanDays] = React.useState(30);
  const [cleanupBusy, setCleanupBusy] = React.useState(false);
  const [cleanupError, setCleanupError] = React.useState("");
  const [summary, setSummary] =
    React.useState<TerminalCleanupResponse | null>(null);

  // sweep-now / rewrite-aof
  const [sweepBusy, setSweepBusy] = React.useState(false);
  const [sweepResult, setSweepResult] =
    React.useState<SweepNowResponse | null>(null);
  const [aofBusy, setAofBusy] = React.useState(false);
  const [actionMsg, setActionMsg] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const data = await getResourceStats();
      setStats(data);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);

  React.useEffect(() => {
    let active = true;
    const tick = async () => {
      const data = await getResourceStats().catch(() => null);
      if (!active) return;
      if (data) {
        setStats(data);
        setLoadError(false);
      } else {
        setLoadError(true);
      }
    };
    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  async function runCleanup(dryRun: boolean) {
    setCleanupError("");
    if (!dryRun) {
      const ok = await confirm({
        title: t("confirm.title"),
        message: t("maintenance.confirmCleanup", { days: olderThanDays }),
        confirmText: t("confirm.confirm"),
        cancelText: t("confirm.cancel"),
        destructive: true,
      });
      if (!ok) return;
    }
    setCleanupBusy(true);
    try {
      setSummary(
        await terminalCleanup({ older_than_days: olderThanDays, dry_run: dryRun }),
      );
    } catch {
      setCleanupError(t("maintenance.cleanupError"));
    } finally {
      setCleanupBusy(false);
    }
  }

  async function runSweep() {
    setActionMsg("");
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("maintenance.confirmSweep"),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    setSweepBusy(true);
    try {
      setSweepResult(await sweepNow());
      void load();
    } catch {
      setActionMsg(t("maintenance.sweepError"));
    } finally {
      setSweepBusy(false);
    }
  }

  async function runRewriteAof() {
    setActionMsg("");
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("maintenance.confirmAof"),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
    });
    if (!ok) return;
    setAofBusy(true);
    try {
      await rewriteAof();
      setActionMsg(t("maintenance.aofStarted"));
    } catch {
      setActionMsg(t("maintenance.aofError"));
    } finally {
      setAofBusy(false);
    }
  }

  const firstSample = stats === null || stats.sampled_at === null;

  return (
    <div className="flex flex-col gap-4" data-testid="maintenance-page">
      {/* Resource dashboard */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>{t("maintenance.dashboardTitle")}</CardTitle>
              <CardDescription>{t("maintenance.dashboardHelp")}</CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              data-testid="maintenance-refresh"
              onClick={() => void load()}
            >
              {t("maintenance.refresh")}
            </Button>
          </div>
          {stats?.sampled_at && (
            <p
              className="text-sm text-muted-foreground"
              data-testid="maintenance-sampled-at"
            >
              {t("maintenance.sampledAt", {
                time: formatDateTime(stats.sampled_at),
              })}
            </p>
          )}
          {stats && !stats.sweep_enabled && (
            <p className="text-sm text-amber-600 dark:text-amber-500">
              {t("maintenance.sweepDisabledNote")}
            </p>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {loadError && (
            <Alert variant="destructive">
              <AlertTitle>{t("maintenance.loadError")}</AlertTitle>
            </Alert>
          )}
          {firstSample ? (
            <div
              className="flex flex-col gap-2"
              data-testid="maintenance-first-sample"
            >
              <p className="text-sm text-muted-foreground">
                {t("maintenance.firstSampleWaiting")}
              </p>
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {stats!.scopes.map((scope) => (
                <ScopeCard key={scope.scope} scope={scope} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Maintenance actions */}
      <Card>
        <CardHeader>
          <CardTitle>{t("maintenance.actionsTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          {/* Terminal-data cleanup */}
          <div className="flex flex-col gap-3">
            <div>
              <h3 className="text-sm font-medium">
                {t("maintenance.cleanupTitle")}
              </h3>
              <p className="text-sm text-muted-foreground">
                {t("maintenance.cleanupHelp")}
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <Field className="w-40">
                <FieldLabel htmlFor="cleanup-days">
                  {t("maintenance.olderThanDays")}
                </FieldLabel>
                <Input
                  id="cleanup-days"
                  type="number"
                  min={0}
                  data-testid="maintenance-days"
                  value={olderThanDays}
                  onChange={(e) =>
                    setOlderThanDays(Math.max(0, Number(e.target.value) || 0))
                  }
                />
              </Field>
              <Button
                variant="outline"
                data-testid="maintenance-preview"
                disabled={cleanupBusy}
                onClick={() => runCleanup(true)}
              >
                {cleanupBusy && <Spinner data-icon="inline-start" />}
                {t("maintenance.preview")}
              </Button>
              <Button
                variant="destructive"
                data-testid="maintenance-run"
                disabled={cleanupBusy}
                onClick={() => runCleanup(false)}
              >
                {cleanupBusy && <Spinner data-icon="inline-start" />}
                {t("maintenance.run")}
              </Button>
            </div>
            {cleanupError && (
              <Alert variant="destructive">
                <AlertTitle>{cleanupError}</AlertTitle>
              </Alert>
            )}
            {summary && (
              <dl
                className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm"
                data-testid="maintenance-summary"
              >
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryMode")}
                </dt>
                <dd>
                  <ToneBadge tone={summary.dry_run ? "gray" : "green"}>
                    {summary.dry_run
                      ? t("maintenance.dryRun")
                      : t("maintenance.deleted")}
                  </ToneBadge>
                </dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryCutoff")}
                </dt>
                <dd>{formatDateTime(summary.cutoff)}</dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryTasks")}
                </dt>
                <dd>{summary.tasks}</dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryExecutions")}
                </dt>
                <dd>{summary.executions}</dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryLogFiles")}
                </dt>
                <dd>{summary.log_files}</dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryLogBytes")}
                </dt>
                <dd>{formatBytes(summary.log_bytes)}</dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryOutbox")}
                </dt>
                <dd>{summary.command_outbox}</dd>
              </dl>
            )}
          </div>

          {/* Sweep now + rewrite AOF */}
          <div className="flex flex-col gap-3">
            <div>
              <h3 className="text-sm font-medium">
                {t("maintenance.sweepTitle")}
              </h3>
              <p className="text-sm text-muted-foreground">
                {t("maintenance.sweepHelp")}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                data-testid="maintenance-sweep"
                disabled={sweepBusy}
                onClick={runSweep}
              >
                {sweepBusy && <Spinner data-icon="inline-start" />}
                {t("maintenance.sweepButton")}
              </Button>
              <Button
                variant="outline"
                data-testid="maintenance-rewrite-aof"
                disabled={aofBusy}
                onClick={runRewriteAof}
              >
                {aofBusy && <Spinner data-icon="inline-start" />}
                {t("maintenance.aofButton")}
              </Button>
            </div>
            {actionMsg && (
              <Alert>
                <AlertTitle>{actionMsg}</AlertTitle>
              </Alert>
            )}
            {sweepResult && (
              <dl
                className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm"
                data-testid="maintenance-sweep-result"
              >
                {(
                  [
                    ["cleanup", "maintenance.stepCleanup"],
                    ["event_audit", "maintenance.stepEventAudit"],
                    ["stream_trim", "maintenance.stepStreamTrim"],
                  ] as const
                ).map(([stepKey, labelKey]) => {
                  const step = sweepResult.steps[stepKey];
                  const status = step?.status ?? "skipped";
                  const tone: Tone =
                    status === "ok"
                      ? "green"
                      : status === "failed"
                        ? "red"
                        : "gray";
                  return (
                    <React.Fragment key={stepKey}>
                      <dt className="text-muted-foreground">{t(labelKey)}</dt>
                      <dd>
                        <ToneBadge tone={tone}>
                          {t(`maintenance.step${status[0].toUpperCase()}${status.slice(1)}`)}
                        </ToneBadge>
                      </dd>
                    </React.Fragment>
                  );
                })}
              </dl>
            )}
          </div>

          <div className="flex flex-col gap-1 text-xs text-muted-foreground">
            <p>{t("maintenance.vacuumNote")}</p>
            <p>{t("maintenance.containerLogNote")}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
