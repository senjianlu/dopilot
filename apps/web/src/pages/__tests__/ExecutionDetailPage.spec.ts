import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { ExecutionView } from "@/api/types";

const sampleExecution: ExecutionView = {
  id: "exec-1",
  task_type: "scrapy",
  target: "demo",
  status: "running",
  node_strategy: "all",
  params: { project: "demo", spider: "phase1" },
  created_at: "2026-06-18T00:00:00Z",
  started_at: "2026-06-18T00:00:01Z",
  finished_at: null,
  attempts: [
    {
      id: "attempt-1",
      execution_id: "exec-1",
      agent_id: "agent-alpha",
      node_id: "n1",
      endpoint: "http://10.0.0.1:6800",
      remote_job_id: "job-xyz",
      status: "running",
      started_at: "2026-06-18T00:00:01Z",
      finished_at: null,
      exit_code: null,
      error_code: null,
      error_detail: null,
    },
  ],
};

const getExecution = vi.fn(async () => sampleExecution);
const cancelExecution = vi.fn(async () => ({
  ...sampleExecution,
  status: "canceled" as const,
}));

vi.mock("@/api/executions", () => ({
  getExecution: () => getExecution(),
  cancelExecution: () => cancelExecution(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "exec-1" } }),
}));

import ExecutionDetailPage from "@/pages/ExecutionDetailPage.vue";

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: "zh",
    fallbackLocale: "en",
    messages: { zh, en },
  });
}

function makeStubs() {
  return {
    "el-card": { template: "<div><slot name='header' /><slot /></div>" },
    "el-empty": { props: ["description"], template: "<div>{{ description }}</div>" },
    "el-alert": { template: "<div><slot /></div>" },
    "el-button": {
      template: "<button @click=\"$emit('click')\"><slot /></button>",
    },
    "el-tag": { template: "<span><slot /></span>" },
    "el-descriptions": { template: "<div><slot /></div>" },
    "el-descriptions-item": {
      props: ["label"],
      template: "<div>{{ label }}<slot /></div>",
    },
    "el-table": { props: ["data"], template: "<div><slot /></div>" },
    "el-table-column": {
      props: ["label", "prop"],
      template: "<div>{{ label }}</div>",
    },
    LogViewer: { template: "<div class='log-viewer-stub' />" },
  };
}

describe("ExecutionDetailPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getExecution.mockClear();
    cancelExecution.mockClear();
  });

  it("renders attempts and cancels via the API", async () => {
    const wrapper = mount(ExecutionDetailPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });

    await flushPromises();

    const vm = wrapper.vm as unknown as {
      execution: ExecutionView | null;
      onCancel: () => Promise<void>;
    };
    expect(getExecution).toHaveBeenCalledTimes(1);
    expect(vm.execution?.attempts).toHaveLength(1);
    expect(vm.execution?.attempts[0].remote_job_id).toBe("job-xyz");
    // The execution detail header renders.
    expect(wrapper.text()).toContain(zh.execution.title);

    await vm.onCancel();
    await flushPromises();

    expect(cancelExecution).toHaveBeenCalledTimes(1);
    expect(vm.execution?.status).toBe("canceled");
  });
});
