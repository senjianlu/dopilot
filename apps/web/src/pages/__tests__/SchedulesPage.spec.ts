import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { ExecutionTemplate, NodeInfo, Schedule } from "@/api/types";

const sampleTemplates: ExecutionTemplate[] = [
  {
    id: "tpl-1",
    name: "demo-template",
    description: null,
    build_artifact_id: "art-1",
    artifact_type: "scrapy",
    project: "demo",
    version: null,
    command: "scrapy crawl phase1",
    node_strategy: "all",
    node_ids: [],
    created_at: "2026-06-19T00:00:00Z",
    updated_at: "2026-06-19T00:00:00Z",
  },
];

const sampleSchedules: Schedule[] = [
  {
    id: "sch-1",
    name: "every-minute",
    description: null,
    execution_template_id: "tpl-1",
    trigger_type: "interval",
    interval_seconds: 60,
    cron: null,
    overrides: {},
    next_run_at: "2026-06-20T12:01:00Z",
    created_at: "2026-06-19T00:00:00Z",
    updated_at: "2026-06-19T00:00:00Z",
  },
];

function makeNode(overrides: Partial<NodeInfo> = {}): NodeInfo {
  return {
    id: "node-1",
    agent_id: "agent-1",
    endpoint: "http://a1:6800",
    status: "healthy",
    capabilities: { scrapy: true },
    health: {},
    last_seen_at: "2026-06-19T00:00:00Z",
    scheduling_enabled: true,
    scheduling_disabled_at: null,
    deleted_at: null,
    ...overrides,
  };
}

const listSchedules = vi.fn(async () => sampleSchedules);
const createSchedule = vi.fn(async (_payload: unknown) => sampleSchedules[0]);
const triggerSchedule = vi.fn(async (_id: string) => ({
  task_id: "task-9",
  status: "queued",
}));
const deleteSchedule = vi.fn(async (_id: string) => undefined);
const previewNextRun = vi.fn(async (_payload: unknown) => ({
  next_run_at: "2026-06-20T12:05:00Z",
}));
const listTemplates = vi.fn(async () => sampleTemplates);
const listNodes = vi.fn(async () => [makeNode()]);

vi.mock("@/api/schedules", () => ({
  listSchedules: () => listSchedules(),
  createSchedule: (payload: unknown) => createSchedule(payload),
  triggerSchedule: (id: string) => triggerSchedule(id),
  deleteSchedule: (id: string) => deleteSchedule(id),
  previewNextRun: (payload: unknown) => previewNextRun(payload),
}));

vi.mock("@/api/templates", () => ({
  listTemplates: () => listTemplates(),
}));

vi.mock("@/api/nodes", () => ({
  listNodes: () => listNodes(),
}));

const confirmAction = vi.fn(async () => true);
vi.mock("@/utils/confirm", () => ({
  confirmAction: () => confirmAction(),
}));

const push = vi.fn();
vi.mock("vue-router", () => ({
  useRouter: () => ({ push }),
}));

import SchedulesPage from "@/pages/SchedulesPage.vue";

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
    "el-button": {
      template: "<button @click=\"$emit('click')\"><slot /></button>",
    },
    "el-table": { props: ["data"], template: "<div class='el-table'><slot /></div>" },
    "el-table-column": {
      props: ["label", "prop"],
      template: "<div class='col'>{{ label }}</div>",
    },
    "el-dialog": { template: "<div><slot /><slot name='footer' /></div>" },
    "el-form": { template: "<form><slot /></form>" },
    "el-form-item": { template: "<div><slot /></div>" },
    "el-input": { template: "<input />" },
    "el-input-number": { template: "<input type='number' />" },
    "el-select": { template: "<select><slot /></select>" },
    "el-option": { template: "<option><slot /></option>" },
    "el-tag": { template: "<span><slot /></span>" },
    "el-alert": { props: ["title"], template: "<div>{{ title }}</div>" },
  };
}

describe("SchedulesPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listSchedules.mockClear();
    createSchedule.mockClear();
    triggerSchedule.mockClear();
    deleteSchedule.mockClear();
    previewNextRun.mockClear();
    listTemplates.mockClear();
    listNodes.mockClear();
    push.mockClear();
    confirmAction.mockClear();
    confirmAction.mockResolvedValue(true);
  });

  it("deletes a schedule only after confirmation", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      onDelete: (s: { id: string; name: string }) => Promise<void>;
    };
    await vm.onDelete({ id: "sch-1", name: "nightly" });
    expect(confirmAction).toHaveBeenCalledTimes(1);
    expect(deleteSchedule).toHaveBeenCalledWith("sch-1");

    confirmAction.mockResolvedValue(false);
    deleteSchedule.mockClear();
    await vm.onDelete({ id: "sch-2", name: "other" });
    expect(deleteSchedule).not.toHaveBeenCalled();
  });

  it("renders trigger time and next run", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      schedules: Schedule[];
      triggerTimeText: (s: Schedule) => string;
      formatTime: (iso: string | null) => string;
    };
    expect(vm.schedules).toHaveLength(1);
    // interval -> "every 60 seconds" (zh: 每 60 秒)
    expect(vm.triggerTimeText(sampleSchedules[0])).toContain("60");
    expect(vm.formatTime(sampleSchedules[0].next_run_at)).not.toBe("-");
  });

  it("shows a local interval estimate on create open", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      estimatedNextRun: string;
    };
    vm.openCreate();
    await flushPromises();
    // interval estimate is computed locally (now + interval), no network call
    expect(vm.estimatedNextRun).not.toBe("");
    expect(previewNextRun).not.toHaveBeenCalled();
  });

  it("fetches a cron estimate from the backend preview", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      form: { trigger_type: string; cron: string };
      updateEstimate: () => Promise<void>;
      estimatedNextRun: string;
    };
    vm.form.trigger_type = "cron";
    vm.form.cron = "*/5 * * * *";
    await vm.updateEstimate();
    expect(previewNextRun).toHaveBeenCalledWith(
      expect.objectContaining({ trigger_type: "cron", cron: "*/5 * * * *" }),
    );
    expect(vm.estimatedNextRun).not.toBe("");
  });

  it("submits an interval create referencing the execution template", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: {
        name: string;
        execution_template_id: string;
        trigger_type: string;
        interval_seconds: number;
        cron: string;
      };
    };
    vm.openCreate();
    vm.form.name = "nightly";
    vm.form.execution_template_id = "tpl-1";
    vm.form.trigger_type = "interval";
    vm.form.interval_seconds = 30;
    await vm.submitCreate();

    expect(createSchedule).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "nightly",
        execution_template_id: "tpl-1",
        trigger_type: "interval",
        interval_seconds: 30,
        cron: null,
      }),
    );
  });

  it("submits a cron create with cron and null interval", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: {
        name: string;
        execution_template_id: string;
        trigger_type: string;
        cron: string;
      };
    };
    vm.openCreate();
    vm.form.name = "cron-job";
    vm.form.execution_template_id = "tpl-1";
    vm.form.trigger_type = "cron";
    vm.form.cron = "*/5 * * * *";
    await vm.submitCreate();

    expect(createSchedule).toHaveBeenCalledWith(
      expect.objectContaining({
        trigger_type: "cron",
        cron: "*/5 * * * *",
        interval_seconds: null,
      }),
    );
  });

  it("includes node overrides when an override strategy is chosen", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: {
        name: string;
        execution_template_id: string;
        override_node_strategy: string;
        override_node_ids: string[];
      };
    };
    vm.openCreate();
    vm.form.name = "override-job";
    vm.form.execution_template_id = "tpl-1";
    vm.form.override_node_strategy = "selected";
    vm.form.override_node_ids = ["node-1"];
    await vm.submitCreate();

    expect(createSchedule).toHaveBeenCalledWith(
      expect.objectContaining({
        overrides: { node_strategy: "selected", node_ids: ["node-1"] },
      }),
    );
  });

  it("includes a command override when one is entered", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: {
        name: string;
        execution_template_id: string;
        override_command: string;
      };
    };
    vm.openCreate();
    vm.form.name = "override-cmd";
    vm.form.execution_template_id = "tpl-1";
    vm.form.override_command = "scrapy crawl phase2 -s LOG_LEVEL=DEBUG";
    await vm.submitCreate();

    expect(createSchedule).toHaveBeenCalledWith(
      expect.objectContaining({
        overrides: { command: "scrapy crawl phase2 -s LOG_LEVEL=DEBUG" },
      }),
    );
  });

  it("blocks submit on an invalid command override", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: { override_command: string };
      canSubmit: boolean;
    };
    vm.openCreate();
    vm.form.override_command = "scrapy crawl phase2 | cat";
    await flushPromises();
    expect(vm.canSubmit).toBe(false);
    await vm.submitCreate();
    expect(createSchedule).not.toHaveBeenCalled();
  });

  it("triggers now and navigates to the created task", async () => {
    const wrapper = mount(SchedulesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      onTrigger: (s: Schedule) => Promise<void>;
    };
    await vm.onTrigger(sampleSchedules[0]);
    expect(triggerSchedule).toHaveBeenCalledWith("sch-1");
    expect(push).toHaveBeenCalledWith("/tasks/task-9");
  });
});
