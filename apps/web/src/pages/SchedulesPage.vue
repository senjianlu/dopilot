<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  previewNextRun,
  triggerSchedule,
} from "@/api/schedules";
import { listTemplates } from "@/api/templates";
import { listNodes } from "@/api/nodes";
import type {
  ExecutionTemplate,
  NodeInfo,
  NodeStrategy,
  Schedule,
  ScheduleOverrides,
  TriggerType,
} from "@/api/types";
import { badgeTagType, nodeBadge } from "@/utils/nodeBadge";
import { checkScrapyCommand } from "@/utils/scrapyCommand";
import { confirmAction } from "@/utils/confirm";

const { t } = useI18n();
const router = useRouter();

const schedules = ref<Schedule[]>([]);
const templates = ref<ExecutionTemplate[]>([]);
const nodes = ref<NodeInfo[]>([]);
const loading = ref(false);
const triggeringId = ref("");
const dialogVisible = ref(false);
const creating = ref(false);
const createError = ref("");
const estimatedNextRun = ref("");

const form = reactive({
  name: "",
  execution_template_id: "",
  trigger_type: "interval" as TriggerType,
  interval_seconds: 60,
  cron: "",
  // override controls (build artifact may NOT be overridden). Phase 1.8.1:
  // command-first — a command override FULLY replaces the template command.
  override_command: "",
  override_node_strategy: "" as "" | NodeStrategy,
  override_node_ids: [] as string[],
});

function nodeKey(node: NodeInfo): string {
  return (node.id ?? node.agent_id ?? node.endpoint) as string;
}

function nodeByKey(key: string): NodeInfo | undefined {
  return nodes.value.find((n) => nodeKey(n) === key);
}

const FALLBACK_NODE = {
  status: "unknown" as const,
  scheduling_enabled: true,
  deleted_at: null,
};

function nodeTagType(key: string) {
  return badgeTagType[nodeBadge(nodeByKey(key) ?? FALLBACK_NODE)];
}

const isSeen = (n: NodeInfo): boolean => n.id != null;

const selectableNodes = computed(() =>
  nodes.value.filter((n) => isSeen(n) && !n.deleted_at && n.scheduling_enabled),
);

const overrideSelectedStrategy = computed(
  () => form.override_node_strategy === "selected",
);

// UX validation for the optional command override (backend authoritative).
const overrideCommandCheck = computed(() =>
  checkScrapyCommand(form.override_command),
);
const overrideCommandError = computed(() =>
  form.override_command && !overrideCommandCheck.value.valid
    ? t(
        `commandErrors.${overrideCommandCheck.value.reason}`,
        t("commandErrors.invalid"),
      )
    : "",
);

function templateName(id: string): string {
  return templates.value.find((tpl) => tpl.id === id)?.name ?? id;
}

// interval -> "every XX seconds"; cron -> the raw expression.
function triggerTimeText(schedule: Schedule): string {
  if (schedule.trigger_type === "cron") {
    return schedule.cron ?? "-";
  }
  return t("schedules.everySeconds", {
    seconds: schedule.interval_seconds ?? 0,
  });
}

function formatTime(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// Recompute the read-only create-dialog estimate. Interval is a local estimate
// (now + interval); cron is resolved by the backend preview endpoint.
async function updateEstimate(): Promise<void> {
  if (form.trigger_type === "interval") {
    if (form.interval_seconds > 0) {
      estimatedNextRun.value = new Date(
        Date.now() + form.interval_seconds * 1000,
      ).toLocaleString();
    } else {
      estimatedNextRun.value = "";
    }
    return;
  }
  if (!form.cron.trim()) {
    estimatedNextRun.value = "";
    return;
  }
  try {
    const res = await previewNextRun({
      trigger_type: "cron",
      cron: form.cron,
    });
    estimatedNextRun.value = res.next_run_at
      ? formatTime(res.next_run_at)
      : t("schedules.nextRunPending");
  } catch {
    estimatedNextRun.value = t("schedules.nextRunPending");
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    [schedules.value, templates.value, nodes.value] = await Promise.all([
      listSchedules(),
      listTemplates(),
      listNodes(),
    ]);
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  form.name = "";
  form.execution_template_id = templates.value[0]?.id ?? "";
  form.trigger_type = "interval";
  form.interval_seconds = 60;
  form.cron = "";
  form.override_command = "";
  form.override_node_strategy = "";
  form.override_node_ids = [];
  createError.value = "";
  dialogVisible.value = true;
  void updateEstimate();
}

// Assemble the optional overrides object (omit empty controls).
function buildOverrides(): ScheduleOverrides | undefined {
  const overrides: ScheduleOverrides = {};
  if (form.override_command.trim()) {
    overrides.command = form.override_command.trim();
  }
  if (form.override_node_strategy) {
    overrides.node_strategy = form.override_node_strategy;
    if (overrideSelectedStrategy.value) {
      overrides.node_ids = form.override_node_ids;
    }
  }
  return Object.keys(overrides).length ? overrides : undefined;
}

const canSubmit = computed(
  () => !form.override_command || overrideCommandCheck.value.valid,
);

async function submitCreate(): Promise<void> {
  if (form.override_command && !overrideCommandCheck.value.valid) {
    createError.value = t("schedules.invalidCommand");
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    await createSchedule({
      name: form.name,
      execution_template_id: form.execution_template_id,
      trigger_type: form.trigger_type,
      interval_seconds:
        form.trigger_type === "interval" ? form.interval_seconds : null,
      cron: form.trigger_type === "cron" ? form.cron : null,
      overrides: buildOverrides(),
    });
    dialogVisible.value = false;
    await load();
  } catch {
    createError.value = t("schedules.createError");
  } finally {
    creating.value = false;
  }
}

async function onTrigger(schedule: Schedule): Promise<void> {
  triggeringId.value = schedule.id;
  try {
    const res = await triggerSchedule(schedule.id);
    await router.push(`/tasks/${res.task_id}`);
  } finally {
    triggeringId.value = "";
  }
}

async function onDelete(schedule: Schedule): Promise<void> {
  const ok = await confirmAction({
    title: t("confirm.title"),
    message: t("schedules.confirmDelete", { name: schedule.name }),
    confirmText: t("confirm.confirm"),
    cancelText: t("confirm.cancel"),
  });
  if (!ok) return;
  await deleteSchedule(schedule.id);
  await load();
}

onMounted(load);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="schedules-header">
        <span>{{ t("schedules.title") }}</span>
        <div class="schedules-actions">
          <el-button type="primary" data-testid="schedule-create" @click="openCreate">
            {{ t("schedules.create") }}
          </el-button>
          <el-button @click="load">{{ t("schedules.refresh") }}</el-button>
        </div>
      </div>
    </template>

    <el-table :data="schedules" :empty-text="t('schedules.empty')" data-testid="schedules-table">
      <el-table-column :label="t('schedules.name')">
        <template #default="{ row }">
          <span :data-testid="`schedule-name-${(row as Schedule).name}`">
            {{ (row as Schedule).name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('schedules.template')">
        <template #default="{ row }">
          {{ templateName((row as Schedule).execution_template_id) }}
        </template>
      </el-table-column>
      <el-table-column
        :label="t('schedules.triggerType')"
        prop="trigger_type"
      />
      <el-table-column :label="t('schedules.triggerTime')">
        <template #default="{ row }">
          {{ triggerTimeText(row as Schedule) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('schedules.nextRun')">
        <template #default="{ row }">
          {{ formatTime((row as Schedule).next_run_at) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('schedules.actions')" width="220">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :data-testid="`schedule-trigger-${(row as Schedule).name}`"
            :loading="triggeringId === (row as Schedule).id"
            @click="onTrigger(row as Schedule)"
          >
            {{ t("schedules.triggerNow") }}
          </el-button>
          <el-button type="danger" link @click="onDelete(row as Schedule)">
            {{ t("schedules.delete") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="t('schedules.createTitle')"
      data-testid="schedule-dialog"
    >
      <el-form label-width="140px">
        <el-form-item :label="t('schedules.name')">
          <el-input v-model="form.name" data-testid="schedule-name-input" />
        </el-form-item>
        <el-form-item :label="t('schedules.template')">
          <el-select
            v-model="form.execution_template_id"
            data-testid="schedule-template-select"
          >
            <el-option
              v-for="tpl in templates"
              :key="tpl.id"
              :label="tpl.name"
              :value="tpl.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('schedules.triggerType')">
          <el-select v-model="form.trigger_type" @change="updateEstimate">
            <el-option :label="t('schedules.intervalType')" value="interval" />
            <el-option :label="t('schedules.cronType')" value="cron" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="form.trigger_type === 'interval'"
          :label="t('schedules.interval')"
        >
          <el-input-number
            v-model="form.interval_seconds"
            data-testid="schedule-interval"
            :min="1"
            @change="updateEstimate"
          />
        </el-form-item>
        <el-form-item v-else :label="t('schedules.cron')">
          <el-input
            v-model="form.cron"
            :placeholder="t('schedules.cronPlaceholder')"
            @input="updateEstimate"
          />
        </el-form-item>
        <el-form-item :label="t('schedules.overrideCommand')">
          <el-input
            v-model="form.override_command"
            data-testid="schedule-command-input"
            :placeholder="t('schedules.overrideCommandNone')"
          />
          <div
            v-if="overrideCommandError"
            class="command-error"
            data-testid="schedule-command-error"
          >
            {{ overrideCommandError }}
          </div>
        </el-form-item>
        <el-form-item :label="t('schedules.overrideStrategy')">
          <el-select
            v-model="form.override_node_strategy"
            :placeholder="t('schedules.overrideStrategyNone')"
            clearable
          >
            <el-option :label="t('schedules.overrideStrategyNone')" value="" />
            <el-option label="all" value="all" />
            <el-option label="random" value="random" />
            <el-option label="selected" value="selected" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="overrideSelectedStrategy"
          :label="t('schedules.overrideNodes')"
        >
          <el-select v-model="form.override_node_ids" multiple>
            <template #tag="{ data, deleteTag }">
              <el-tag
                v-for="item in data"
                :key="item.value"
                :type="nodeTagType(item.value)"
                closable
                disable-transitions
                @close="deleteTag($event, item)"
              >
                {{ nodeByKey(item.value)?.agent_id ?? item.currentLabel }}
              </el-tag>
            </template>
            <el-option
              v-for="n in selectableNodes"
              :key="nodeKey(n)"
              :label="n.agent_id ?? n.endpoint"
              :value="nodeKey(n)"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('schedules.estimatedNextRun')">
          <span class="next-run-estimate">{{ estimatedNextRun || "-" }}</span>
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
          {{ t("schedules.cancel") }}
        </el-button>
        <el-button
          type="primary"
          data-testid="schedule-submit"
          :loading="creating"
          :disabled="!canSubmit"
          @click="submitCreate"
        >
          {{ t("schedules.submit") }}
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.schedules-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.schedules-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.next-run-estimate {
  color: var(--el-text-color-secondary);
}
.command-error {
  color: var(--el-color-danger);
  font-size: 12px;
  margin-top: 4px;
}
</style>
