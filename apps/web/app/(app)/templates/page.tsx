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
import { listBuildArtifacts } from "@/lib/api/artifacts";
import { listNodes } from "@/lib/api/nodes";
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
  runTemplate,
} from "@/lib/api/templates";
import type {
  BuildArtifact,
  ExecutionTemplate,
  NodeInfo,
  NodeStrategy,
} from "@/lib/api/types";
import { nodeBadge } from "@/lib/nodeBadge";
import {
  nodeKey,
  schedulableNodes as schedulableNodesOf,
  selectableNodes as selectableNodesOf,
} from "@/lib/nodeSelection";
import { commandCheckFor, defaultCommand } from "@/lib/templateCommand";
import { useConfirm } from "@/hooks/use-confirm";

export default function TemplatesPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const confirm = useConfirm();

  const [templates, setTemplates] = React.useState<ExecutionTemplate[]>([]);
  const [artifacts, setArtifacts] = React.useState<BuildArtifact[]>([]);
  const [nodes, setNodes] = React.useState<NodeInfo[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [runningId, setRunningId] = React.useState("");
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState("");

  const [name, setName] = React.useState("");
  const [buildArtifactId, setBuildArtifactId] = React.useState("");
  const [command, setCommand] = React.useState("");
  const [nodeStrategy, setNodeStrategy] = React.useState<NodeStrategy>("all");
  const [nodeIds, setNodeIds] = React.useState<string[]>([]);
  const prevArtifactId = React.useRef("");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [tpls, arts, nds] = await Promise.all([
        listTemplates(),
        listBuildArtifacts(),
        listNodes(),
      ]);
      setTemplates(tpls);
      setArtifacts(arts);
      setNodes(nds);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const schedulableNodes = React.useMemo(
    () => schedulableNodesOf(nodes),
    [nodes],
  );
  const selectableNodes = React.useMemo(
    () => selectableNodesOf(nodes),
    [nodes],
  );
  const isSelectedStrategy = nodeStrategy === "selected";

  const runnableArtifacts = React.useMemo(
    () => artifacts.filter((a) => a.runnable),
    [artifacts],
  );
  const selectedArtifact = React.useMemo(
    () => artifacts.find((a) => a.id === buildArtifactId),
    [artifacts, buildArtifactId],
  );
  const availableSpiders = selectedArtifact?.spiders ?? [];
  const isWheel = selectedArtifact?.artifact_type === "python_wheel";
  const resolvedProject = selectedArtifact?.project ?? "-";
  const resolvedVersion = selectedArtifact?.version ?? "-";

  // Phase 2b: a python_wheel command is free-form (non-empty only); the scrapy
  // parser must NOT run against a shell command.
  const commandCheck = commandCheckFor(!!isWheel, command);
  const commandError = (() => {
    if (!command || commandCheck.valid) return "";
    if (isWheel) return t("commandErrors.empty");
    return t(`commandErrors.${commandCheck.reason}`, t("commandErrors.invalid"));
  })();

  // When the artifact changes and the command is still the prior default, swap
  // in the new artifact's default command (mirrors the old Vue watcher).
  React.useEffect(() => {
    if (buildArtifactId === prevArtifactId.current) return;
    const prevArt = artifacts.find((a) => a.id === prevArtifactId.current);
    const wasDefault = !command || command === defaultCommand(prevArt);
    if (wasDefault) {
      setCommand(defaultCommand(selectedArtifact));
    }
    prevArtifactId.current = buildArtifactId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildArtifactId]);

  // Drop now-unselectable nodes when switching to the `selected` strategy.
  React.useEffect(() => {
    if (isSelectedStrategy) {
      const allowed = new Set(selectableNodes.map(nodeKey));
      setNodeIds((ids) => ids.filter((id) => allowed.has(id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeStrategy]);

  const canSubmit = !!command && commandCheck.valid && !!selectedArtifact;

  function openCreate() {
    const first = runnableArtifacts[0];
    setName("");
    setBuildArtifactId(first?.id ?? "");
    prevArtifactId.current = first?.id ?? "";
    setCommand(defaultCommand(first));
    setNodeStrategy("all");
    setNodeIds([]);
    setCreateError("");
    setDialogOpen(true);
  }

  function toggleNode(key: string) {
    setNodeIds((ids) =>
      ids.includes(key) ? ids.filter((id) => id !== key) : [...ids, key],
    );
  }

  async function submitCreate() {
    const art = selectedArtifact;
    if (!art) {
      setCreateError(t("templates.createError"));
      return;
    }
    if (!commandCheck.valid) {
      setCreateError(t("templates.invalidCommand"));
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      await createTemplate({
        name,
        build_artifact_id: art.id,
        command: command.trim(),
        node_strategy: nodeStrategy,
        node_ids: isSelectedStrategy ? nodeIds : [],
      });
      setDialogOpen(false);
      await load();
    } catch {
      setCreateError(t("templates.createError"));
    } finally {
      setCreating(false);
    }
  }

  async function onRun(template: ExecutionTemplate) {
    setRunningId(template.id);
    try {
      const res = await runTemplate(template.id);
      router.push(`/tasks/detail?id=${res.task_id}`);
    } finally {
      setRunningId("");
    }
  }

  async function onDelete(template: ExecutionTemplate) {
    const ok = await confirm({
      title: t("confirm.title"),
      message: t("templates.confirmDelete", { name: template.name }),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
      destructive: true,
    });
    if (!ok) return;
    await deleteTemplate(template.id);
    await load();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("templates.title")}</CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            <Button data-testid="template-create" onClick={openCreate}>
              {t("templates.create")}
            </Button>
            <Button variant="outline" onClick={load}>
              {t("templates.refresh")}
            </Button>
          </div>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table data-testid="templates-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("templates.name")}</TableHead>
              <TableHead>{t("templates.command")}</TableHead>
              <TableHead>{t("templates.version")}</TableHead>
              <TableHead>{t("templates.strategy")}</TableHead>
              <TableHead className="text-right">
                {t("templates.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {templates.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="text-muted-foreground text-center"
                >
                  {loading ? "…" : t("templates.empty")}
                </TableCell>
              </TableRow>
            ) : (
              templates.map((tpl) => (
                <TableRow key={tpl.id}>
                  <TableCell data-testid={`template-name-${tpl.name}`}>
                    {tpl.name}
                  </TableCell>
                  <TableCell>
                    <code
                      className="text-xs"
                      data-testid={`template-command-${tpl.name}`}
                    >
                      {tpl.command ?? "-"}
                    </code>
                  </TableCell>
                  <TableCell>{tpl.version ?? "-"}</TableCell>
                  <TableCell>{tpl.node_strategy}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`template-run-${tpl.name}`}
                      disabled={runningId === tpl.id}
                      onClick={() => onRun(tpl)}
                    >
                      {runningId === tpl.id && (
                        <Spinner data-icon="inline-start" />
                      )}
                      {t("templates.run")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive"
                      onClick={() => onDelete(tpl)}
                    >
                      {t("templates.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="template-dialog" className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("templates.createTitle")}</DialogTitle>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="tpl-name">{t("templates.name")}</FieldLabel>
              <Input
                id="tpl-name"
                data-testid="template-name-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel>{t("templates.buildArtifact")}</FieldLabel>
              <Select value={buildArtifactId} onValueChange={setBuildArtifactId}>
                <SelectTrigger
                  className="w-full"
                  data-testid="template-artifact-select"
                >
                  <SelectValue placeholder={t("templates.selectArtifact")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {runnableArtifacts.map((a) => (
                      <SelectItem key={a.id} value={a.id}>
                        {`${a.name} · ${a.filename ?? a.id}`}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>{t("templates.project")}</FieldLabel>
              <Input data-testid="template-project" value={resolvedProject} disabled readOnly />
            </Field>
            <Field>
              <FieldLabel>{t("templates.version")}</FieldLabel>
              <Input data-testid="template-version" value={resolvedVersion} disabled readOnly />
            </Field>
            <Field data-invalid={!!commandError || undefined}>
              <FieldLabel htmlFor="tpl-command">
                {isWheel ? t("templates.shellCommand") : t("templates.command")}
              </FieldLabel>
              <Input
                id="tpl-command"
                data-testid="template-command-input"
                aria-invalid={!!commandError || undefined}
                placeholder={
                  isWheel
                    ? t("templates.shellCommandPlaceholder")
                    : t("templates.commandPlaceholder")
                }
                value={command}
                onChange={(e) => setCommand(e.target.value)}
              />
              {commandError ? (
                <FieldError data-testid="template-command-error">
                  {commandError}
                </FieldError>
              ) : isWheel ? (
                <FieldDescription data-testid="template-command-hint">
                  {t("templates.shellCommandHint")}
                </FieldDescription>
              ) : availableSpiders.length ? (
                <FieldDescription>
                  {t("templates.commandSpiders", {
                    spiders: availableSpiders.join(", "),
                  })}
                </FieldDescription>
              ) : null}
            </Field>
            <Field>
              <FieldLabel>{t("templates.strategy")}</FieldLabel>
              <Select
                value={nodeStrategy}
                onValueChange={(v) => setNodeStrategy(v as NodeStrategy)}
              >
                <SelectTrigger className="w-full" data-testid="template-strategy-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="all">all</SelectItem>
                    <SelectItem value="random">random</SelectItem>
                    <SelectItem value="selected">selected</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>{t("templates.involvedNodes")}</FieldLabel>
              {isSelectedStrategy ? (
                <div
                  className="flex flex-wrap gap-2"
                  data-testid="template-node-picker"
                >
                  {selectableNodes.length === 0 && (
                    <span className="text-muted-foreground text-sm">
                      {t("templates.selectNodes")}
                    </span>
                  )}
                  {selectableNodes.map((n) => {
                    const key = nodeKey(n);
                    const active = nodeIds.includes(key);
                    return (
                      <button
                        type="button"
                        key={key}
                        onClick={() => toggleNode(key)}
                        data-testid={`template-node-${n.agent_id}`}
                        aria-pressed={active}
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
              ) : (
                <div className="flex flex-wrap gap-2">
                  {schedulableNodes.length === 0 ? (
                    <span className="text-muted-foreground text-sm">
                      {t("templates.involvedNodesAuto")}
                    </span>
                  ) : (
                    schedulableNodes.map((n) => (
                      <ToneBadge key={nodeKey(n)} tone={NODE_BADGE_TONE[nodeBadge(n)]}>
                        {n.agent_id ?? n.endpoint}
                      </ToneBadge>
                    ))
                  )}
                </div>
              )}
            </Field>
            {createError && (
              <Alert variant="destructive">
                <AlertTitle>{createError}</AlertTitle>
              </Alert>
            )}
          </FieldGroup>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t("templates.cancel")}
            </Button>
            <Button
              data-testid="template-submit"
              disabled={!canSubmit || creating}
              onClick={submitCreate}
            >
              {creating && <Spinner data-icon="inline-start" />}
              {t("templates.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
