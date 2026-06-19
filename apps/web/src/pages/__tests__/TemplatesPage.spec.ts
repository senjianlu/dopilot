import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { TaskTemplate } from "@/api/types";

const sampleTemplates: TaskTemplate[] = [
  {
    id: "tpl-1",
    name: "demo-template",
    description: null,
    task_type: "scrapy",
    project: "demo",
    version: null,
    spider: "phase1",
    artifact: {},
    settings: {},
    args: {},
    node_strategy: "all",
    node_ids: [],
    created_at: "2026-06-19T00:00:00Z",
    updated_at: "2026-06-19T00:00:00Z",
  },
];

const listTemplates = vi.fn(async () => sampleTemplates);
const createTemplate = vi.fn(async (_payload: unknown) => sampleTemplates[0]);
const runTemplate = vi.fn(async (_id: string) => ({
  execution_id: "exec-9",
  status: "queued",
}));
const deleteTemplate = vi.fn(async (_id: string) => undefined);

vi.mock("@/api/templates", () => ({
  listTemplates: () => listTemplates(),
  createTemplate: (payload: unknown) => createTemplate(payload),
  runTemplate: (id: string) => runTemplate(id),
  deleteTemplate: (id: string) => deleteTemplate(id),
}));

const push = vi.fn();
vi.mock("vue-router", () => ({
  useRouter: () => ({ push }),
}));

import TemplatesPage from "@/pages/TemplatesPage.vue";

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
    "el-select": { template: "<select><slot /></select>" },
    "el-option": { template: "<option><slot /></option>" },
    "el-alert": { props: ["title"], template: "<div>{{ title }}</div>" },
  };
}

describe("TemplatesPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listTemplates.mockClear();
    createTemplate.mockClear();
    runTemplate.mockClear();
  });

  it("renders fetched templates", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    expect(wrapper.text()).toContain(zh.templates.title);
    const vm = wrapper.vm as unknown as { templates: TaskTemplate[] };
    expect(vm.templates).toHaveLength(1);
    expect(vm.templates[0].name).toBe("demo-template");
  });

  it("submits a create with the chosen node strategy", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: { name: string; project: string; spider: string; node_strategy: string };
    };
    vm.openCreate();
    vm.form.name = "t2";
    vm.form.project = "demo";
    vm.form.spider = "s";
    vm.form.node_strategy = "random";
    await vm.submitCreate();

    expect(createTemplate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "t2", node_strategy: "random" }),
    );
  });

  it("runs a template and navigates to the created task", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      onRun: (t: TaskTemplate) => Promise<void>;
    };
    await vm.onRun(sampleTemplates[0]);
    expect(runTemplate).toHaveBeenCalledWith("tpl-1");
    expect(push).toHaveBeenCalledWith("/executions/exec-9");
  });
});
