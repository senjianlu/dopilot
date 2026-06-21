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
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Field, FieldLabel } from "@/components/ui/field";
import { ToneBadge } from "@/components/features/status-badge";
import { terminalCleanup } from "@/lib/api/maintenance";
import type { TerminalCleanupResponse } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { useConfirm } from "@/hooks/use-confirm";

export default function MaintenancePage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [olderThanDays, setOlderThanDays] = React.useState(30);
  const [running, setRunning] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState("");
  const [summary, setSummary] = React.useState<TerminalCleanupResponse | null>(
    null,
  );

  const logBytesMB = summary
    ? `${(summary.log_bytes / (1024 * 1024)).toFixed(2)} MB`
    : "0.00 MB";

  async function run(dryRun: boolean) {
    setErrorMsg("");
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
    setRunning(true);
    try {
      setSummary(
        await terminalCleanup({
          older_than_days: olderThanDays,
          dry_run: dryRun,
        }),
      );
    } catch {
      setErrorMsg(t("maintenance.cleanupError"));
    } finally {
      setRunning(false);
    }
  }

  return (
    <Card data-testid="maintenance-page">
      <CardHeader>
        <CardTitle>{t("maintenance.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t("maintenance.cleanupTitle")}
            </CardTitle>
            <CardDescription>{t("maintenance.cleanupHelp")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
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
                disabled={running}
                onClick={() => run(true)}
              >
                {running && <Spinner data-icon="inline-start" />}
                {t("maintenance.preview")}
              </Button>
              <Button
                variant="destructive"
                data-testid="maintenance-run"
                disabled={running}
                onClick={() => run(false)}
              >
                {running && <Spinner data-icon="inline-start" />}
                {t("maintenance.run")}
              </Button>
            </div>

            {errorMsg && (
              <Alert variant="destructive">
                <AlertTitle>{errorMsg}</AlertTitle>
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
                <dd>
                  {summary.log_files}
                  {!summary.dry_run && (
                    <span className="text-muted-foreground">
                      {" "}
                      (
                      {t("maintenance.summaryRemoved", {
                        n: summary.log_files_removed,
                      })}
                      )
                    </span>
                  )}
                </dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryLogBytes")}
                </dt>
                <dd>{logBytesMB}</dd>
                <dt className="text-muted-foreground">
                  {t("maintenance.summaryOutbox")}
                </dt>
                <dd>{summary.command_outbox}</dd>
              </dl>
            )}
          </CardContent>
        </Card>
      </CardContent>
    </Card>
  );
}
