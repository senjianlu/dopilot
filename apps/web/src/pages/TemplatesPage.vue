<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { listBuildArtifacts } from "@/api/artifacts";
import { listNodes } from "@/api/nodes";
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
  runTemplate,
} from "@/api/templates";
import type {
  BuildArtifact,
  ExecutionTemplate,
  NodeInfo,
  NodeStrategy,
} from "@/api/types";
import { badgeTagType, nodeBadge } from "@/utils/nodeBadge";
import { checkScrapyCommand } from "@/utils/scrapyCommand";
import { confirmAction } from "@/utils/confirm";

const { t } = useI18n();
const router = useRouter();

const templates = ref<ExecutionTemplate[]>([]);
const artifacts = ref<BuildArtifact[]>([]);
const nodes = ref<NodeInfo[]>([]);
const loading = ref(false);
const runningId = ref("");
const dialogVisible = ref(false);
const creating = ref(false);
const createError = ref("");

const form = reactive({
  name: "",
  buildArtifactId: "",
  command: "",
  node_strategy: "all" as NodeStrategy,
  node_ids: [] as string[],
});

function nodeKey(node: NodeInfo): string {
  return (node.id ?? node.agent_id ?? node.endpoint) as string;
}

// Configured-but-unseen endpoints (id == null) have never produced a DB row, so
// backend selected-node resolution (matches DB id or agent_id) can never target
// them — selecting one persists a value that yields `no_target`. Exclude them
// from both the all/random involvement display and the `selected` pick list.
const isSeen = (n: NodeInfo): boolean => n.id != null;

// non-deleted + schedulable (= eligible for all/random involvement display).
const schedulableNodes = computed(() =>
  nodes.value.filter((n) => isSeen(n) && !n.deleted_at && n.scheduling_enabled),
);
// selectable for `selected`: non-deleted + non-offline (regardless of health).
// Offline/deleted/unseen nodes may NOT be newly selected.
const selectableNodes = computed(() =>
  nodes.value.filter((n) => isSeen(n) && !n.deleted_at && n.scheduling_enabled),
);

const isSelectedStrategy = computed(() => form.node_strategy === "selected");

// Options shown in the multi-select; for all/random it is informational.
const nodeOptions = computed(() =>
  isSelectedStrategy.value ? selectableNodes.value : schedulableNodes.value,
);

// The multi-select's bound value. For all/random the model is the full
// schedulable set (disabled/read-only). For selected it is the user's choice.
const selectedNodeIds = computed<string[]>({
  get() {
    return isSelectedStrategy.value
      ? form.node_ids
      : schedulableNodes.value.map(nodeKey);
  },
  set(value: string[]) {
    if (isSelectedStrategy.value) {
      form.node_ids = value;
    }
  },
});

// Resolve a node id back to its row so we can colour the selected tags.
function nodeByKey(key: string): NodeInfo | undefined {
  return nodes.value.find((n) => nodeKey(n) === key);
}

const FALLBACK_NODE = {
  status: "unknown" as const,
  scheduling_enabled: true,
  deleted_at: null,
};

// Element Plus tag type for a selected node id (status colour inside the input).
function nodeTagType(key: string) {
  return badgeTagType[nodeBadge(nodeByKey(key) ?? FALLBACK_NODE)];
}

// Only runnable artifacts can back a template.
const runnableArtifacts = computed(() =>
  artifacts.value.filter((a) => a.runnable),
);

const selectedArtifact = computed(() =>
  artifacts.value.find((a) => a.id === form.buildArtifactId),
);
const availableSpiders = computed(() => selectedArtifact.value?.spiders ?? []);

// Read-only project/version resolved from the selected artifact.
const resolvedProject = computed(() => selectedArtifact.value?.project ?? "-");
const resolvedVersion = computed(() => selectedArtifact.value?.version ?? "-");

// Phase 1.8.1: command-first. UX validation of the command (backend remains
// authoritative). `commandError` blocks submit and shows an inline reason.
const commandCheck = computed(() => checkScrapyCommand(form.command));
const commandError = computed(() =>
  form.command && !commandCheck.value.valid
    ? t(`commandErrors.${commandCheck.value.reason}`, t("commandErrors.invalid"))
    : "",
);

// Default the command from the artifact's first spider when it changes and the
// user has not typed a custom command yet.
function defaultCommand(art: BuildArtifact | undefined): string {
  const spider = art?.spiders?.[0];
  return spider ? `scrapy crawl ${spider}` : "";
}
watch(
  () => form.buildArtifactId,
  (_id, prev) => {
    const wasDefault =
      !form.command ||
      form.command === defaultCommand(artifacts.value.find((a) => a.id === prev));
    if (wasDefault) {
      form.command = defaultCommand(selectedArtifact.value);
    }
  },
);

// Drop selected nodes that are no longer selectable when switching to selected.
watch(
  () => form.node_strategy,
  () => {
    if (isSelectedStrategy.value) {
      const allowed = new Set(selectableNodes.value.map(nodeKey));
      form.node_ids = form.node_ids.filter((id) => allowed.has(id));
    }
  },
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    [templates.value, artifacts.value, nodes.value] = await Promise.all([
      listTemplates(),
      listBuildArtifacts(),
      listNodes(),
    ]);
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  form.name = "";
  const first = runnableArtifacts.value[0];
  form.buildArtifactId = first?.id ?? "";
  form.command = defaultCommand(first);
  form.node_strategy = "all";
  form.node_ids = [];
  createError.value = "";
  dialogVisible.value = true;
}

// Block submit on an empty/invalid command (UX only).
const canSubmit = computed(
  () => !!form.command && commandCheck.value.valid && !!selectedArtifact.value,
);

async function submitCreate(): Promise<void> {
  const art = selectedArtifact.value;
  if (!art) {
    createError.value = t("templates.createError");
    return;
  }
  if (!commandCheck.value.valid) {
    createError.value = t("templates.invalidCommand");
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    await createTemplate({
      name: form.name,
      build_artifact_id: art.id,
      command: form.command.trim(),
      node_strategy: form.node_strategy,
      node_ids: isSelectedStrategy.value ? form.node_ids : [],
    });
    dialogVisible.value = false;
    await load();
  } catch {
    createError.value = t("templates.createError");
  } finally {
    creating.value = false;
  }
}

async function onRun(template: ExecutionTemplate): Promise<void> {
  runningId.value = template.id;
  try {
    const res = await runTemplate(template.id);
    await router.push(`/tasks/${res.task_id}`);
  } finally {
    runningId.value = "";
  }
}

async function onDelete(template: ExecutionTemplate): Promise<void> {
  const ok = await confirmAction({
    title: t("confirm.title"),
    message: t("templates.confirmDelete", { name: template.name }),
    confirmText: t("confirm.confirm"),
    cancelText: t("confirm.cancel"),
  });
  if (!ok) return;
  await deleteTemplate(template.id);
  await load();
}

onMounted(load);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="templates-header">
        <span>{{ t("templates.title") }}</span>
        <div class="templates-actions">
          <el-button type="primary" data-testid="template-create" @click="openCreate">
            {{ t("templates.create") }}
          </el-button>
          <el-button @click="load">{{ t("templates.refresh") }}</el-button>
        </div>
      </div>
    </template>

    <el-table :data="templates" :empty-text="t('templates.empty')" data-testid="templates-table">
      <el-table-column :label="t('templates.name')">
        <template #default="{ row }">
          <span :data-testid="`template-name-${(row as ExecutionTemplate).name}`">
            {{ (row as ExecutionTemplate).name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('templates.command')">
        <template #default="{ row }">
          <code :data-testid="`template-command-${(row as ExecutionTemplate).name}`">
            {{ (row as ExecutionTemplate).command ?? "-" }}
          </code>
        </template>
      </el-table-column>
      <el-table-column :label="t('templates.version')" prop="version" />
      <el-table-column
        :label="t('templates.strategy')"
        prop="node_strategy"
      />
      <el-table-column :label="t('templates.actions')" width="200">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :data-testid="`template-run-${(row as ExecutionTemplate).name}`"
            :loading="runningId === (row as ExecutionTemplate).id"
            @click="onRun(row as ExecutionTemplate)"
          >
            {{ t("templates.run") }}
          </el-button>
          <el-button
            type="danger"
            link
            @click="onDelete(row as ExecutionTemplate)"
          >
            {{ t("templates.delete") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="t('templates.createTitle')"
      data-testid="template-dialog"
    >
      <el-form label-width="140px">
        <el-form-item :label="t('templates.name')">
          <el-input v-model="form.name" data-testid="template-name-input" />
        </el-form-item>
        <el-form-item :label="t('templates.buildArtifact')">
          <el-select
            v-model="form.buildArtifactId"
            data-testid="template-artifact-select"
            :placeholder="t('templates.selectArtifact')"
            :no-data-text="t('templates.noArtifacts')"
          >
            <el-option
              v-for="a in runnableArtifacts"
              :key="a.id"
              :label="`${a.name} · ${a.filename ?? a.id}`"
              :value="a.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('templates.project')">
          <el-input
            :model-value="resolvedProject"
            data-testid="template-project"
            disabled
          />
        </el-form-item>
        <el-form-item :label="t('templates.version')">
          <el-input
            :model-value="resolvedVersion"
            data-testid="template-version"
            disabled
          />
        </el-form-item>
        <el-form-item :label="t('templates.command')">
          <el-input
            v-model="form.command"
            data-testid="template-command-input"
            :placeholder="t('templates.commandPlaceholder')"
          />
          <div
            v-if="commandError"
            class="command-error"
            data-testid="template-command-error"
          >
            {{ commandError }}
          </div>
          <div v-else-if="availableSpiders.length" class="command-hint">
            {{ t("templates.commandSpiders", { spiders: availableSpiders.join(", ") }) }}
          </div>
        </el-form-item>
        <el-form-item :label="t('templates.strategy')">
          <el-select v-model="form.node_strategy">
            <el-option label="all" value="all" />
            <el-option label="random" value="random" />
            <el-option label="selected" value="selected" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('templates.involvedNodes')">
          <el-select
            v-model="selectedNodeIds"
            multiple
            :disabled="!isSelectedStrategy"
            :placeholder="
              isSelectedStrategy
                ? t('templates.selectNodes')
                : t('templates.involvedNodesAuto')
            "
          >
            <!-- status colour rendered on the tags INSIDE the input (no
                 duplicate chips below). -->
            <template #tag="{ data, deleteTag }">
              <el-tag
                v-for="item in data"
                :key="item.value"
                :type="nodeTagType(item.value)"
                :closable="isSelectedStrategy"
                disable-transitions
                @close="deleteTag($event, item)"
              >
                {{ nodeByKey(item.value)?.agent_id ?? item.currentLabel }}
              </el-tag>
            </template>
            <el-option
              v-for="n in nodeOptions"
              :key="nodeKey(n)"
              :label="n.agent_id ?? n.endpoint"
              :value="nodeKey(n)"
            />
          </el-select>
        </el-form-item>
        <el-alert
          v-if="createError"
          :title="createError"
          type="error"
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">
          {{ t("templates.cancel") }}
        </el-button>
        <el-button
          type="primary"
          data-testid="template-submit"
          :loading="creating"
          :disabled="!canSubmit"
          @click="submitCreate"
        >
          {{ t("templates.submit") }}
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.templates-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.templates-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.command-error {
  color: var(--el-color-danger);
  font-size: 12px;
  margin-top: 4px;
}
.command-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}
</style>
