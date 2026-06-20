<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  listBuildArtifacts,
  runBuildArtifact,
  uploadEgg,
} from "@/api/artifacts";
import type { BuildArtifact } from "@/api/types";

const { t } = useI18n();
const router = useRouter();
const artifacts = ref<BuildArtifact[]>([]);
const loading = ref(false);
const uploading = ref(false);
const runningId = ref("");
const uploadRef = ref();

async function load(): Promise<void> {
  loading.value = true;
  try {
    artifacts.value = await listBuildArtifacts();
  } finally {
    loading.value = false;
  }
}

async function onUpload(options: { file: File }): Promise<void> {
  uploading.value = true;
  try {
    await uploadEgg({ file: options.file });
    uploadRef.value?.clearFiles?.();
    await load();
  } finally {
    uploading.value = false;
  }
}

function shortHash(hash: string | null): string {
  if (!hash) return "-";
  return `${hash.slice(0, 12)}…`;
}

async function runArtifact(artifact: BuildArtifact): Promise<void> {
  const spider = artifact.spiders[0];
  if (!spider) {
    return;
  }
  runningId.value = artifact.id;
  try {
    const res = await runBuildArtifact(artifact.id, {
      spider,
      node_strategy: "all",
    });
    await router.push(`/tasks/${res.task_id}`);
  } finally {
    runningId.value = "";
  }
}

onMounted(load);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="artifacts-header">
        <span>{{ t("artifacts.title") }}</span>
        <div class="artifacts-actions">
          <el-upload
            ref="uploadRef"
            data-testid="artifact-upload"
            :http-request="onUpload"
            :show-file-list="false"
            :disabled="uploading"
            accept=".egg"
          >
            <el-button type="primary" data-testid="artifact-upload-button" :loading="uploading">
              {{ t("artifacts.upload") }}
            </el-button>
          </el-upload>
          <el-button @click="load">{{ t("artifacts.refresh") }}</el-button>
        </div>
      </div>
    </template>
    <el-table :data="artifacts" :empty-text="t('artifacts.empty')" data-testid="artifacts-table">
      <el-table-column :label="t('artifacts.name')">
        <template #default="{ row }">
          <span :data-testid="`artifact-name-${(row as BuildArtifact).name}`">
            {{ (row as BuildArtifact).name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.type')">
        <template #default="{ row }">
          <span :data-testid="`artifact-type-${(row as BuildArtifact).name}`">
            {{ (row as BuildArtifact).artifact_type }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.format')">
        <template #default="{ row }">
          <span :data-testid="`artifact-format-${(row as BuildArtifact).name}`">
            {{ (row as BuildArtifact).package_format }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.filename')" prop="filename" />
      <el-table-column :label="t('artifacts.spiders')">
        <template #default="{ row }">
          {{ (row as BuildArtifact).spiders.join(", ") }}
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.hash')">
        <template #default="{ row }">
          {{ shortHash((row as BuildArtifact).content_hash) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.sizeBytes')" prop="size_bytes" />
      <el-table-column :label="t('artifacts.status')">
        <template #default="{ row }">
          <el-tag :type="(row as BuildArtifact).runnable ? 'success' : 'info'">
            {{ (row as BuildArtifact).runnable ? "runnable" : "n/a" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.actions')" width="120">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :data-testid="`artifact-run-${(row as BuildArtifact).name}`"
            :loading="runningId === (row as BuildArtifact).id"
            :disabled="!(row as BuildArtifact).runnable || !(row as BuildArtifact).spiders.length"
            @click="runArtifact(row as BuildArtifact)"
          >
            {{ t("artifacts.run") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.artifacts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.artifacts-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
