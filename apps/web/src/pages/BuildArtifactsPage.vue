<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { listBuildArtifacts, uploadEgg, uploadWheel } from "@/api/artifacts";
import type { BuildArtifact } from "@/api/types";

const { t } = useI18n();
const artifacts = ref<BuildArtifact[]>([]);
const loading = ref(false);
const uploading = ref(false);
const uploadingWheel = ref(false);
const uploadRef = ref();
const uploadWheelRef = ref();

// Details dialog state.
const detailsVisible = ref(false);
const selected = ref<BuildArtifact | null>(null);

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

async function onUploadWheel(options: { file: File }): Promise<void> {
  uploadingWheel.value = true;
  try {
    await uploadWheel({ file: options.file });
    uploadWheelRef.value?.clearFiles?.();
    await load();
  } finally {
    uploadingWheel.value = false;
  }
}

function shortHash(hash: string | null): string {
  if (!hash) return "-";
  return `${hash.slice(0, 12)}…`;
}

// Display raw bytes as MB (e.g. "1.23 MB"). Raw bytes stay untouched in API data.
function formatMB(sizeBytes: number): string {
  const mb = (sizeBytes || 0) / (1024 * 1024);
  return `${mb.toFixed(2)} MB`;
}

function openDetails(artifact: BuildArtifact): void {
  selected.value = artifact;
  detailsVisible.value = true;
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
          <el-upload
            ref="uploadWheelRef"
            data-testid="artifact-upload-wheel"
            :http-request="onUploadWheel"
            :show-file-list="false"
            :disabled="uploadingWheel"
            accept=".whl"
          >
            <el-button
              type="primary"
              data-testid="artifact-upload-wheel-button"
              :loading="uploadingWheel"
            >
              {{ t("artifacts.uploadWheel") }}
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
      <el-table-column :label="t('artifacts.hash')">
        <template #default="{ row }">
          {{ shortHash((row as BuildArtifact).content_hash) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('artifacts.size')">
        <template #default="{ row }">
          <span :data-testid="`artifact-size-${(row as BuildArtifact).name}`">
            {{ formatMB((row as BuildArtifact).size_bytes) }}
          </span>
        </template>
      </el-table-column>
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
            :data-testid="`artifact-details-${(row as BuildArtifact).name}`"
            @click="openDetails(row as BuildArtifact)"
          >
            {{ t("artifacts.details") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="detailsVisible"
      :title="t('artifacts.detailsTitle')"
      data-testid="artifact-details-dialog"
      width="560px"
    >
      <el-descriptions v-if="selected" :column="1" border>
        <el-descriptions-item :label="t('artifacts.name')">
          {{ selected.name }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('artifacts.type')">
          {{ selected.artifact_type }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('artifacts.format')">
          {{ selected.package_format }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('artifacts.filename')">
          {{ selected.filename ?? "-" }}
        </el-descriptions-item>
        <el-descriptions-item
          v-if="selected.artifact_type === 'python_wheel'"
          :label="t('artifacts.distribution')"
        >
          {{ selected.distribution ?? "-" }}
        </el-descriptions-item>
        <el-descriptions-item v-else :label="t('artifacts.project')">
          {{ selected.project ?? "-" }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('artifacts.version')">
          {{ selected.version ?? "-" }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('artifacts.hash')">
          <span class="artifact-hash">{{ selected.content_hash ?? "-" }}</span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('artifacts.size')">
          {{ formatMB(selected.size_bytes) }}
        </el-descriptions-item>
      </el-descriptions>

      <!-- Spiders shown as read-only tags inside a bounded, textarea-like area.
           The tags are NOT editable (no close handles, no input). Python wheels
           have no spiders, so the section is scrapy-only. -->
      <div v-if="selected?.artifact_type !== 'python_wheel'" class="spiders-label">
        {{ t("artifacts.spiders") }}
      </div>
      <div
        v-if="selected?.artifact_type !== 'python_wheel'"
        class="spiders-box"
        data-testid="artifact-details-spiders"
      >
        <template v-if="selected && selected.spiders.length">
          <el-tag
            v-for="s in selected.spiders"
            :key="s"
            class="spider-tag"
            type="info"
            disable-transitions
          >
            {{ s }}
          </el-tag>
        </template>
        <span v-else class="spiders-empty">{{ t("artifacts.noSpiders") }}</span>
      </div>

      <template #footer>
        <el-button data-testid="artifact-details-close" @click="detailsVisible = false">
          {{ t("artifacts.close") }}
        </el-button>
      </template>
    </el-dialog>
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

.spiders-label {
  margin: 16px 0 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* Bounded, scrollable, textarea-like container holding the read-only tags. */
.spiders-box {
  min-height: 72px;
  max-height: 160px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: var(--el-fill-color-blank);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-content: flex-start;
}

.spider-tag {
  margin: 0;
}

.spiders-empty {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}

.artifact-hash {
  word-break: break-all;
}
</style>
