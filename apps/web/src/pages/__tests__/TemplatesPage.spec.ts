import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { NodeInfo, ScrapyArtifact, TaskTemplate } from "@/api/types";

const sampleTemplates: TaskTemplate[] = [
  {
    id: "tpl-1",
    name: "demo-template",
    description: null,
    task_type: "scrapy",
    project: "demo",
    version: "v1",
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

const sampleArtifacts: ScrapyArtifact[] = [
  {
    id: "sha-abc",
    project: "demo",
    version: "v1",
    filename: "demo.egg",
    sha256: "sha-abc",
    size_bytes: 1024,
    spiders: ["phase1", "phase2"],
    valid: true,
    uploaded_at: "2026-06-19T00:00:00Z",
    created_at: "2026-06-19T00:00:00Z",
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

const sampleNodes: NodeInfo[] = [
  makeNode(),
  makeNode({ id: "node-2", agent_id: "agent-2", scheduling_enabled: false }),
  makeNode({ id: "node-3", agent_id: "agent-3", deleted_at: "2026-06-20T00:00:00Z" }),
  // configured-but-unseen endpoint (no DB id): cannot be resolved by the
  // backend, so it must be excluded from involved + selectable sets.
  makeNode({ id: null, agent_id: null, endpoint: "http://a4:6800" }),
];

const listTemplates = vi.fn(async () => sampleTemplates);
const createTemplate = vi.fn(async (_payload: unknown) => sampleTemplates[0]);
const runTemplate = vi.fn(async (_id: string) => ({
  execution_id: "exec-9",
  status: "queued",
}));
const deleteTemplate = vi.fn(async (_id: string) => undefined);
const listScrapyArtifacts = vi.fn(async () => sampleArtifacts);
const listNodes = vi.fn(async () => sampleNodes);

vi.mock("@/api/templates", () => ({
  listTemplates: () => listTemplates(),
  createTemplate: (payload: unknown) => createTemplate(payload),
  runTemplate: (id: string) => runTemplate(id),
  deleteTemplate: (id: string) => deleteTemplate(id),
}));
vi.mock("@/api/artifacts", () => ({
  listScrapyArtifacts: () => listScrapyArtifacts(),
}));
vi.mock("@/api/nodes", () => ({
  listNodes: () => listNodes(),
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
    "el-select": {
      props: ["disabled", "modelValue"],
      template: "<select :disabled='disabled'><slot /></select>",
    },
    "el-option": { template: "<option><slot /></option>" },
    "el-tag": { template: "<span><slot /></span>" },
    "el-alert": { props: ["title"], template: "<div>{{ title }}</div>" },
  };
}

describe("TemplatesPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listTemplates.mockClear();
    createTemplate.mockClear();
    runTemplate.mockClear();
    listScrapyArtifacts.mockClear();
    listNodes.mockClear();
  });

  it("renders fetched templates (no project column)", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    expect(wrapper.text()).toContain(zh.templates.title);
    // Project column header is gone.
    expect(wrapper.text()).not.toContain(zh.templates.project);
    const vm = wrapper.vm as unknown as { templates: TaskTemplate[] };
    expect(vm.templates).toHaveLength(1);
  });

  it("submits a derived payload from the chosen artifact + spider", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: { name: string; artifactHash: string; spider: string };
    };
    vm.openCreate();
    vm.form.name = "t2";
    vm.form.artifactHash = "sha-abc";
    vm.form.spider = "phase2";
    await vm.submitCreate();

    expect(createTemplate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "t2",
        project: "demo",
        version: "v1",
        spider: "phase2",
        artifact: expect.objectContaining({
          sha256: "sha-abc",
          fetch_path: "/api/v1/artifacts/scrapy/sha-abc/egg",
        }),
      }),
    );
  });

  it("node selector locks for all/random and unlocks for selected", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      form: { node_strategy: string; node_ids: string[] };
      isSelectedStrategy: boolean;
      selectableNodes: NodeInfo[];
      schedulableNodes: NodeInfo[];
      selectedNodeIds: string[];
    };

    // all -> locked, model shows all schedulable nodes
    vm.form.node_strategy = "all";
    await flushPromises();
    expect(vm.isSelectedStrategy).toBe(false);
    // node-2 (offline) and node-3 (deleted) are not schedulable
    expect(vm.schedulableNodes.map((n) => n.id)).toEqual(["node-1"]);
    expect(vm.selectedNodeIds).toEqual(["node-1"]);

    // selected -> unlocked, only non-deleted non-offline nodes selectable
    vm.form.node_strategy = "selected";
    await flushPromises();
    expect(vm.isSelectedStrategy).toBe(true);
    expect(vm.selectableNodes.map((n) => n.id)).toEqual(["node-1"]);
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