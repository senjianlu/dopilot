<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { terminalCleanup } from "@/api/maintenance";
import type { TerminalCleanupResponse } from "@/api/types";
import { confirmAction } from "@/utils/confirm";

const { t } = useI18n();

const olderThanDays = ref(30);
const running = ref(false);
const errorMsg = ref("");
const summary = ref<TerminalCleanupResponse | null>(null);

const logBytesMB = computed(() => {
  if (!summary.value) return "0.00 MB";
  return `${(summary.value.log_bytes / (1024 * 1024)).toFixed(2)} MB`;
});

async function run(dryRun: boolean): Promise<void> {
  errorMsg.value = "";
  if (!dryRun) {
    const ok = await confirmAction({
      title: t("confirm.title"),
      message: t("maintenance.confirmCleanup", { days: olderThanDays.value }),
      confirmText: t("confirm.confirm"),
      cancelText: t("confirm.cancel"),
    });
    if (!ok) return;
  }
  running.value = true;
  try {
    summary.value = await terminalCleanup({
      older_than_days: olderThanDays.value,
      dry_run: dryRun,
    });
  } catch {
    errorMsg.value = t("maintenance.cleanupError");
  } finally {
    running.value = false;
  }
}
</script>

<template>
  <el-card data-testid="maintenance-page">
    <template #header>
      <span>{{ t("maintenance.title") }}</span>
    </template>

    <el-card shadow="never" class="cleanup-card">
      <template #header>
        <span>{{ t("maintenance.cleanupTitle") }}</span>
      </template>
      <p class="cleanup-help">{{ t("maintenance.cleanupHelp") }}</p>
      <el-form inline @submit.prevent>
        <el-form-item :label="t('maintenance.olderThanDays')">
          <el-input-number
            v-model="olderThanDays"
            data-testid="maintenance-days"
            :min="0"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            data-testid="maintenance-preview"
            :loading="running"
            @click="run(true)"
          >
            {{ t("maintenance.preview") }}
          </el-button>
          <el-button
            type="danger"
            data-testid="maintenance-run"
            :loading="running"
            @click="run(false)"
          >
            {{ t("maintenance.run") }}
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        :closable="false"
        show-icon
      />

      <el-descriptions
        v-if="summary"
        :column="2"
        border
        data-testid="maintenance-summary"
        class="cleanup-summary"
      >
        <el-descriptions-item :label="t('maintenance.summaryMode')">
          <el-tag :type="summary.dry_run ? 'info' : 'success'">
            {{ summary.dry_run ? t("maintenance.dryRun") : t("maintenance.deleted") }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="t('maintenance.summaryCutoff')">
          {{ summary.cutoff }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('maintenance.summaryTasks')">
          {{ summary.tasks }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('maintenance.summaryExecutions')">
          {{ summary.executions }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('maintenance.summaryLogFiles')">
          {{ summary.log_files }}
          <span v-if="!summary.dry_run">
            ({{ t("maintenance.summaryRemoved", { n: summary.log_files_removed }) }})
          </span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('maintenance.summaryLogBytes')">
          {{ logBytesMB }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('maintenance.summaryOutbox')">
          {{ summary.command_outbox }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </el-card>
</template>

<style scoped>
.cleanup-card {
  margin-top: 4px;
}
.cleanup-help {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.cleanup-summary {
  margin-top: 16px;
}
</style>
