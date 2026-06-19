<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
  runTemplate,
} from "@/api/templates";
import type { NodeStrategy, TaskTemplate } from "@/api/types";

const { t } = useI18n();
const router = useRouter();

const templates = ref<TaskTemplate[]>([]);
const loading = ref(false);
const runningId = ref("");
const dialogVisible = ref(false);
const creating = ref(false);
const createError = ref("");

const form = reactive({
  name: "",
  project: "",
  spider: "",
  version: "",
  node_strategy: "all" as NodeStrategy,
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    templates.value = await listTemplates();
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  form.name = "";
  form.project = "";
  form.spider = "";
  form.version = "";
  form.node_strategy = "all";
  createError.value = "";
  dialogVisible.value = true;
}

async function submitCreate(): Promise<void> {
  creating.value = true;
  createError.value = "";
  try {
    await createTemplate({
      name: form.name,
      project: form.project,
      spider: form.spider,
      version: form.version || null,
      node_strategy: form.node_strategy,
    });
    dialogVisible.value = false;
    await load();
  } catch {
    createError.value = t("templates.createError");
  } finally {
    creating.value = false;
  }
}

async function onRun(template: TaskTemplate): Promise<void> {
  runningId.value = template.id;
  try {
    const res = await runTemplate(template.id);
    await router.push(`/executions/${res.execution_id}`);
  } finally {
    runningId.value = "";
  }
}

async function onDelete(template: TaskTemplate): Promise<void> {
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
          <el-button type="primary" @click="openCreate">
            {{ t("templates.create") }}
          </el-button>
          <el-button @click="load">{{ t("templates.refresh") }}</el-button>
        </div>
      </div>
    </template>

    <el-table :data="templates" :empty-text="t('templates.empty')">
      <el-table-column :label="t('templates.name')" prop="name" />
      <el-table-column :label="t('templates.project')" prop="project" />
      <el-table-column :label="t('templates.spider')" prop="spider" />
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
            :loading="runningId === (row as TaskTemplate).id"
            @click="onRun(row as TaskTemplate)"
          >
            {{ t("templates.run") }}
          </el-button>
          <el-button
            type="danger"
            link
            @click="onDelete(row as TaskTemplate)"
          >
            {{ t("templates.delete") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="t('templates.createTitle')">
      <el-form label-width="120px">
        <el-form-item :label="t('templates.name')">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item :label="t('templates.project')">
          <el-input v-model="form.project" />
        </el-form-item>
        <el-form-item :label="t('templates.spider')">
          <el-input v-model="form.spider" />
        </el-form-item>
        <el-form-item :label="t('templates.version')">
          <el-input
            v-model="form.version"
            :placeholder="t('templates.versionPlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('templates.strategy')">
          <el-select v-model="form.node_strategy">
            <el-option label="all" value="all" />
            <el-option label="random" value="random" />
            <el-option label="selected" value="selected" />
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
        <el-button type="primary" :loading="creating" @click="submitCreate">
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
</style>
