<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { runExecution } from "@/api/executions";
import type { NodeStrategy, RunExecutionRequest } from "@/api/types";

const { t } = useI18n();
const router = useRouter();

interface KvRow {
  key: string;
  value: string;
}

const form = reactive({
  project: "",
  version: "",
  spider: "",
  nodeStrategy: "all" as NodeStrategy,
  nodeIds: "",
});

const args = ref<KvRow[]>([{ key: "", value: "" }]);
const settings = ref<KvRow[]>([{ key: "", value: "" }]);
const loading = ref(false);
const errorMsg = ref("");

const strategyOptions = computed(() => [
  { value: "all" as NodeStrategy, label: t("run.strategyAll") },
  { value: "random" as NodeStrategy, label: t("run.strategyRandom") },
  { value: "selected" as NodeStrategy, label: t("run.strategySelected") },
]);

function addRow(rows: KvRow[]): void {
  rows.push({ key: "", value: "" });
}

// Collapse the key/value rows into a record, dropping blank keys.
function rowsToRecord(rows: KvRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key) {
      out[key] = row.value;
    }
  }
  return out;
}

function parseNodeIds(): string[] {
  return form.nodeIds
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

async function onSubmit(): Promise<void> {
  errorMsg.value = "";
  loading.value = true;
  try {
    const payload: RunExecutionRequest = {
      task_type: "scrapy",
      target: form.project,
      node_strategy: form.nodeStrategy,
      node_ids: form.nodeStrategy === "selected" ? parseNodeIds() : [],
      params: {
        project: form.project,
        spider: form.spider,
        ...(form.version.trim() ? { version: form.version.trim() } : {}),
        settings: rowsToRecord(settings.value),
        args: rowsToRecord(args.value),
      },
    };
    const res = await runExecution(payload);
    await router.push({
      name: "execution-detail",
      params: { id: res.execution_id },
    });
  } catch {
    errorMsg.value = t("run.submitError");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <span>{{ t("run.title") }}</span>
    </template>
    <el-form label-position="top" @submit.prevent="onSubmit">
      <el-form-item :label="t('run.project')">
        <el-input v-model="form.project" />
      </el-form-item>
      <el-form-item :label="t('run.spider')">
        <el-input v-model="form.spider" />
      </el-form-item>
      <el-form-item :label="t('run.version')">
        <el-input
          v-model="form.version"
          :placeholder="t('run.versionPlaceholder')"
        />
      </el-form-item>
      <el-form-item :label="t('run.nodeStrategy')">
        <el-select v-model="form.nodeStrategy" class="strategy-select">
          <el-option
            v-for="opt in strategyOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item
        v-if="form.nodeStrategy === 'selected'"
        :label="t('run.nodeIds')"
      >
        <el-input
          v-model="form.nodeIds"
          :placeholder="t('run.nodeIdsPlaceholder')"
        />
      </el-form-item>

      <el-form-item :label="t('run.args')">
        <div class="kv-list">
          <div v-for="(row, i) in args" :key="`arg-${i}`" class="kv-row">
            <el-input
              v-model="row.key"
              :placeholder="t('run.keyPlaceholder')"
            />
            <el-input
              v-model="row.value"
              :placeholder="t('run.valuePlaceholder')"
            />
          </div>
          <el-button text @click="addRow(args)">{{
            t("run.addRow")
          }}</el-button>
        </div>
      </el-form-item>

      <el-form-item :label="t('run.settings')">
        <div class="kv-list">
          <div v-for="(row, i) in settings" :key="`set-${i}`" class="kv-row">
            <el-input
              v-model="row.key"
              :placeholder="t('run.keyPlaceholder')"
            />
            <el-input
              v-model="row.value"
              :placeholder="t('run.valuePlaceholder')"
            />
          </div>
          <el-button text @click="addRow(settings)">{{
            t("run.addRow")
          }}</el-button>
        </div>
      </el-form-item>

      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        :closable="false"
        show-icon
      />
      <el-form-item>
        <el-button
          type="primary"
          :loading="loading"
          native-type="submit"
          @click="onSubmit"
        >
          {{ t("run.submit") }}
        </el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.strategy-select {
  width: 240px;
}
.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.kv-row {
  display: flex;
  gap: 8px;
}
</style>
