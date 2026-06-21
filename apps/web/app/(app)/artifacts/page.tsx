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
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ToneBadge } from "@/components/features/status-badge";
import { listBuildArtifacts, uploadEgg, uploadWheel } from "@/lib/api/artifacts";
import type { BuildArtifact } from "@/lib/api/types";

function shortHash(hash: string | null): string {
  if (!hash) return "-";
  return `${hash.slice(0, 12)}…`;
}

function formatMB(sizeBytes: number): string {
  const mb = (sizeBytes || 0) / (1024 * 1024);
  return `${mb.toFixed(2)} MB`;
}

export default function BuildArtifactsPage() {
  const { t } = useTranslation();
  const [artifacts, setArtifacts] = React.useState<BuildArtifact[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [uploadingEgg, setUploadingEgg] = React.useState(false);
  const [uploadingWheel, setUploadingWheel] = React.useState(false);
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [selected, setSelected] = React.useState<BuildArtifact | null>(null);
  const eggInput = React.useRef<HTMLInputElement | null>(null);
  const wheelInput = React.useRef<HTMLInputElement | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setArtifacts(await listBuildArtifacts());
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function onEggChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploadingEgg(true);
    try {
      await uploadEgg({ file });
      await load();
    } finally {
      setUploadingEgg(false);
    }
  }

  async function onWheelChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploadingWheel(true);
    try {
      await uploadWheel({ file });
      await load();
    } finally {
      setUploadingWheel(false);
    }
  }

  function openDetails(artifact: BuildArtifact) {
    setSelected(artifact);
    setDetailsOpen(true);
  }

  const isWheel = selected?.artifact_type === "python_wheel";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("artifacts.title")}</CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            <div data-testid="artifact-upload">
              <input
                ref={eggInput}
                type="file"
                accept=".egg"
                className="hidden"
                onChange={onEggChange}
              />
              <Button
                data-testid="artifact-upload-button"
                disabled={uploadingEgg}
                onClick={() => eggInput.current?.click()}
              >
                {uploadingEgg && <Spinner data-icon="inline-start" />}
                {t("artifacts.upload")}
              </Button>
            </div>
            <div data-testid="artifact-upload-wheel">
              <input
                ref={wheelInput}
                type="file"
                accept=".whl"
                className="hidden"
                onChange={onWheelChange}
              />
              <Button
                data-testid="artifact-upload-wheel-button"
                disabled={uploadingWheel}
                onClick={() => wheelInput.current?.click()}
              >
                {uploadingWheel && <Spinner data-icon="inline-start" />}
                {t("artifacts.uploadWheel")}
              </Button>
            </div>
            <Button variant="outline" onClick={load}>
              {t("artifacts.refresh")}
            </Button>
          </div>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table data-testid="artifacts-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("artifacts.name")}</TableHead>
              <TableHead>{t("artifacts.type")}</TableHead>
              <TableHead>{t("artifacts.format")}</TableHead>
              <TableHead>{t("artifacts.filename")}</TableHead>
              <TableHead>{t("artifacts.hash")}</TableHead>
              <TableHead>{t("artifacts.size")}</TableHead>
              <TableHead>{t("artifacts.status")}</TableHead>
              <TableHead className="text-right">
                {t("artifacts.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {artifacts.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="text-muted-foreground text-center"
                >
                  {loading ? "…" : t("artifacts.empty")}
                </TableCell>
              </TableRow>
            ) : (
              artifacts.map((a) => (
                <TableRow key={a.id}>
                  <TableCell data-testid={`artifact-name-${a.name}`}>
                    {a.name}
                  </TableCell>
                  <TableCell data-testid={`artifact-type-${a.name}`}>
                    {a.artifact_type}
                  </TableCell>
                  <TableCell data-testid={`artifact-format-${a.name}`}>
                    {a.package_format}
                  </TableCell>
                  <TableCell>{a.filename ?? "-"}</TableCell>
                  <TableCell>{shortHash(a.content_hash)}</TableCell>
                  <TableCell data-testid={`artifact-size-${a.name}`}>
                    {formatMB(a.size_bytes)}
                  </TableCell>
                  <TableCell>
                    <ToneBadge tone={a.runnable ? "green" : "gray"}>
                      {a.runnable
                        ? t("artifacts.runnable")
                        : t("artifacts.notRunnable")}
                    </ToneBadge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`artifact-details-${a.name}`}
                      onClick={() => openDetails(a)}
                    >
                      {t("artifacts.details")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>

      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent
          data-testid="artifact-details-dialog"
          className="sm:max-w-xl"
        >
          <DialogHeader>
            <DialogTitle>{t("artifacts.detailsTitle")}</DialogTitle>
          </DialogHeader>
          {selected && (
            <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">{t("artifacts.name")}</dt>
              <dd>{selected.name}</dd>
              <dt className="text-muted-foreground">{t("artifacts.type")}</dt>
              <dd>{selected.artifact_type}</dd>
              <dt className="text-muted-foreground">{t("artifacts.format")}</dt>
              <dd>{selected.package_format}</dd>
              <dt className="text-muted-foreground">
                {t("artifacts.filename")}
              </dt>
              <dd>{selected.filename ?? "-"}</dd>
              {isWheel ? (
                <>
                  <dt className="text-muted-foreground">
                    {t("artifacts.distribution")}
                  </dt>
                  <dd>{selected.distribution ?? "-"}</dd>
                </>
              ) : (
                <>
                  <dt className="text-muted-foreground">
                    {t("artifacts.project")}
                  </dt>
                  <dd>{selected.project ?? "-"}</dd>
                </>
              )}
              <dt className="text-muted-foreground">
                {t("artifacts.version")}
              </dt>
              <dd>{selected.version ?? "-"}</dd>
              <dt className="text-muted-foreground">{t("artifacts.hash")}</dt>
              <dd className="break-all">{selected.content_hash ?? "-"}</dd>
              <dt className="text-muted-foreground">{t("artifacts.size")}</dt>
              <dd>{formatMB(selected.size_bytes)}</dd>
            </dl>
          )}

          {selected && !isWheel && (
            <div className="flex flex-col gap-2">
              <div className="text-muted-foreground text-sm">
                {t("artifacts.spiders")}
              </div>
              <div
                data-testid="artifact-details-spiders"
                className="flex max-h-40 min-h-18 flex-wrap content-start gap-1.5 overflow-y-auto rounded-md border p-2"
              >
                {selected.spiders.length ? (
                  selected.spiders.map((s) => (
                    <ToneBadge key={s} tone="gray">
                      {s}
                    </ToneBadge>
                  ))
                ) : (
                  <span className="text-muted-foreground text-sm">
                    {t("artifacts.noSpiders")}
                  </span>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              data-testid="artifact-details-close"
              onClick={() => setDetailsOpen(false)}
            >
              {t("artifacts.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
