<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useAuthStore } from "@/stores/auth";
import { buildStreamUrl, fetchStreamToken } from "@/api/executions";

const props = defineProps<{
  executionId: string;
  attemptId?: string;
  stream?: string;
}>();

const { t } = useI18n();
const auth = useAuthStore();

const content = ref("");
const completed = ref(false);
const errored = ref(false);
const bodyRef = ref<HTMLElement | null>(null);

let source: EventSource | null = null;

function close(): void {
  if (source) {
    source.close();
    source = null;
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = bodyRef.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
}

function onLog(event: MessageEvent): void {
  try {
    const payload = JSON.parse(event.data) as { content?: string };
    if (payload.content) {
      content.value += payload.content;
      void scrollToBottom();
    }
  } catch {
    // Ignore malformed frames; the server controls the JSON shape.
  }
}

function onComplete(): void {
  completed.value = true;
  close();
}

function onError(): void {
  // EventSource auto-reconnects on transient errors; only surface a hard
  // failure once the stream is closed.
  if (source && source.readyState === EventSource.CLOSED) {
    errored.value = true;
  }
}

async function connect(): Promise<void> {
  close();
  content.value = "";
  completed.value = false;
  errored.value = false;

  // When web auth is on, EventSource cannot send the bearer header, so fetch a
  // short-lived stream token and pass it as a query param.
  let streamToken: string | undefined;
  if (!auth.isAuthOff) {
    try {
      const res = await fetchStreamToken(props.executionId);
      streamToken = res.stream_token;
    } catch {
      errored.value = true;
      return;
    }
  }

  const url = buildStreamUrl(props.executionId, {
    attemptId: props.attemptId,
    stream: props.stream,
    streamToken,
  });
  source = new EventSource(url);
  source.addEventListener("log", onLog as EventListener);
  source.addEventListener("complete", onComplete);
  source.addEventListener("error", onError);
}

watch(
  () => [props.executionId, props.attemptId, props.stream],
  () => {
    void connect();
  },
  { immediate: true },
);

onBeforeUnmount(close);
</script>

<template>
  <div class="log-viewer">
    <div class="log-header">
      <span>{{ t("logs.title") }}</span>
      <el-tag v-if="completed" type="success" size="small">
        {{ t("logs.complete") }}
      </el-tag>
      <el-tag v-else-if="errored" type="danger" size="small">
        {{ t("logs.error") }}
      </el-tag>
    </div>
    <pre ref="bodyRef" class="log-body">{{
      content || t("logs.waiting")
    }}</pre>
  </div>
</template>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.log-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.log-body {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
