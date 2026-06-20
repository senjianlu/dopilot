<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
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
import type { Schedule, TaskTemplate, TriggerType } from "@/api/types";

const { t } = useI18n();
const router = useRouter();

const schedules = ref<Schedule[]>([]);
const templates = ref<TaskTemplate[]>([]);
const loading = ref(false);
const triggeringId = ref("");
const dialogVisible = ref(false);
const creating = ref(false);
const createError = ref("");
const estimatedNextRun = ref("");

const form = reactive({
  name: "",
  template_id: "",
  trigger_type: "interval" as TriggerType,
  interval_seconds: 60,
  cron: "",
});

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
    [schedules.value, templates.value] = await Promise.all([
      listSchedules(),
      listTemplates(),
    ]);
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  form.name = "";
  form.template_id = templates.value[0]?.id ?? "";
  form.trigger_type = "interval";
  form.interval_seconds = 60;
  form.cron = "";
  createError.value = "";
  dialogVisible.value = true;
  void updateEstimate();
}

async function submitCreate(): Promise<void> {
  creating.value = true;
  createError.value = "";
  try {
    await createSchedule({
      name: form.name,
      template_id: form.template_id,
      trigger_type: form.trigger_type,
      interval_seconds:
        form.trigger_type === "interval" ? form.interval_seconds : null,
      cron: form.trigger_type === "cron" ? form.cron : null,
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
    await router.push(`/executions/${res.execution_id}`);
  } finally {
    triggeringId.value = "";
  }
}

async function onDelete(schedule: Schedule): Promise<void> {
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
          <el-button type="primary" @click="openCreate">
            {{ t("schedules.create") }}
          </el-button>
          <el-button @click="load">{{ t("schedules.refresh") }}</el-button>
        </div>
      </div>
    </template>

    <el-table :data="schedules" :empty-text="t('schedules.empty')">
      <el-table-column :label="t('schedules.name')" prop="name" />
      <el-table-column :label="t('schedules.template')">
        <template #default="{ row }">
          {{ templateName((row as Schedule).template_id) }}
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

    <el-dialog v-model="dialogVisible" :title="t('schedules.createTitle')">
      <el-form label-width="120px">
        <el-form-item :label="t('schedules.name')">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item :label="t('schedules.template')">
          <el-select v-model="form.template_id">
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
        <el-button type="primary" :loading="creating" @click="submitCreate">
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
</style>