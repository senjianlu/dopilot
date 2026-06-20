import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { TaskView } from "@/api/types";

const sampleTask: TaskView = {
  id: "task-1",
  artifact_type: "scrapy",
  target: "demo",
  status: "running",
  node_strategy: "all",
  params: { project: "demo", spider: "phase1" },
  build_artifact: { id: "art-1", project: "demo" },
  created_at: "2026-06-18T00:00:00Z",
  started_at: "2026-06-18T00:00:01Z",
  finished_at: null,
  executions: [
    {
      id: "exec-1",
      task_id: "task-1",
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

const getTask = vi.fn(async () => sampleTask);
const cancelTask = vi.fn(async () => ({
  ...sampleTask,
  status: "canceled" as const,
}));

const markTaskLost = vi.fn(async () => ({
  task_id: "task-1",
  task_status: "lost",
  executions_marked: 1,
  already_terminal: [],
}));

vi.mock("@/api/tasks", () => ({
  getTask: () => getTask(),
  cancelTask: () => cancelTask(),
}));

vi.mock("@/api/maintenance", () => ({
  markTaskLost: () => markTaskLost(),
}));

// Confirmations are driven explicitly per test; default to confirmed.
const confirmAction = vi.fn(async () => true);
vi.mock("@/utils/confirm", () => ({
  confirmAction: () => confirmAction(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "task-1" } }),
}));

import TaskDetailPage from "@/pages/TaskDetailPage.vue";

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

describe("TaskDetailPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getTask.mockClear();
    cancelTask.mockClear();
    markTaskLost.mockClear();
    confirmAction.mockClear();
    confirmAction.mockResolvedValue(true);
  });

  it("renders executions and cancels via the API (after confirm)", async () => {
    const wrapper = mount(TaskDetailPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });

    await flushPromises();

    const vm = wrapper.vm as unknown as {
      task: TaskView | null;
      onCancel: () => Promise<void>;
    };
    expect(getTask).toHaveBeenCalledTimes(1);
    expect(vm.task?.executions).toHaveLength(1);
    expect(vm.task?.executions[0].remote_job_id).toBe("job-xyz");
    // The task detail header renders.
    expect(wrapper.text()).toContain(zh.task.title);

    await vm.onCancel();
    await flushPromises();

    expect(confirmAction).toHaveBeenCalledTimes(1);
    expect(cancelTask).toHaveBeenCalledTimes(1);
    expect(vm.task?.status).toBe("canceled");
  });

  it("does NOT cancel when the confirmation is declined", async () => {
    confirmAction.mockResolvedValue(false);
    const wrapper = mount(TaskDetailPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as { onCancel: () => Promise<void> };
    await vm.onCancel();
    await flushPromises();
    expect(confirmAction).toHaveBeenCalledTimes(1);
    expect(cancelTask).not.toHaveBeenCalled();
  });

  it("marks the task lost via the API after confirm", async () => {
    const wrapper = mount(TaskDetailPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as { onMarkLost: () => Promise<void> };
    await vm.onMarkLost();
    await flushPromises();
    expect(confirmAction).toHaveBeenCalledTimes(1);
    expect(markTaskLost).toHaveBeenCalledTimes(1);
    // The page reloads the task after marking lost.
    expect(getTask).toHaveBeenCalledTimes(2);
  });

  it("does NOT mark lost when the confirmation is declined", async () => {
    confirmAction.mockResolvedValue(false);
    const wrapper = mount(TaskDetailPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as { onMarkLost: () => Promise<void> };
    await vm.onMarkLost();
    await flushPromises();
    expect(markTaskLost).not.toHaveBeenCalled();
  });
});
