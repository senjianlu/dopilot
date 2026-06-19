<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { listScrapyArtifacts, uploadEgg } from "@/api/artifacts";
import { runExecution } from "@/api/executions";
import type { ScrapyArtifact } from "@/api/types";

const { t } = useI18n();
const router = useRouter();
const artifacts = ref<ScrapyArtifact[]>([]);
const loading = ref(false);
const uploading = ref(false);
const runningHash = ref("");
const uploadRef = ref();

async function load(): Promise<void> {
  loading.value = true;
  try {
    artifacts.value = await listScrapyArtifacts();
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

function shortHash(hash: string): string {
  return `${hash.slice(0, 12)}…`;
}

async function runArtifact(artifact: ScrapyArtifact): Promise<void> {
  const spider = artifact.spiders[0];
  if (!spider) {
    return;
  }
  runningHash.value = artifact.sha256;
  try {
    const res = await runExecution({
      task_type: "scrapy",
      target: `${artifact.project}:${spider}`,
      node_strategy: "all",
      node_ids: [],
      params: {
        spider,
        artifact: {
          hash: artifact.sha256,
          sha256: artifact.sha256,
          filename: artifact.filename,
          project: artifact.project,
          version: artifact.version,
          size_bytes: artifact.size_bytes,
          fetch_path: `/api/v1/artifacts/scrapy/${artifact.sha256}/egg`,
        },
      },
    });
    await router.push(`/executions/${res.execution_id}`);
  } finally {
    runningHash.value = "";
  }
}

onMounted(load);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="crawlers-header">
        <span>{{ t("crawlers.title") }}</span>
        <div class="crawlers-actions">
          <el-upload
            ref="uploadRef"
            :http-request="onUpload"
            :show-file-list="false"
            :disabled="uploading"
            accept=".egg"
          >
            <el-button type="primary" :loading="uploading">
              {{ t("crawlers.upload") }}
            </el-button>
          </el-upload>
          <el-button @click="load">{{ t("executions.refresh") }}</el-button>
        </div>
      </div>
    </template>
    <el-table :data="artifacts" :empty-text="t('crawlers.empty')">
      <el-table-column :label="t('crawlers.filename')" prop="filename" />
      <el-table-column :label="t('crawlers.spiders')">
        <template #default="{ row }">
          {{ (row as ScrapyArtifact).spiders.join(", ") }}
        </template>
      </el-table-column>
      <el-table-column :label="t('crawlers.hash')">
        <template #default="{ row }">
          {{ shortHash((row as ScrapyArtifact).sha256) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('crawlers.uploadedAt')" prop="uploaded_at" />
      <el-table-column :label="t('crawlers.sizeBytes')" prop="size_bytes" />
      <el-table-column :label="t('crawlers.status')">
        <template #default="{ row }">
          <el-tag :type="(row as ScrapyArtifact).valid ? 'success' : 'danger'">
            {{ (row as ScrapyArtifact).valid ? "valid" : "invalid" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('crawlers.actions')" width="120">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :loading="runningHash === (row as ScrapyArtifact).sha256"
            :disabled="!(row as ScrapyArtifact).valid || !(row as ScrapyArtifact).spiders.length"
            @click="runArtifact(row as ScrapyArtifact)"
          >
            {{ t("crawlers.run") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.crawlers-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.crawlers-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
