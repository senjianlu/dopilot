import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { BuildArtifact, ExecutionTemplate, NodeInfo } from "@/api/types";

const sampleTemplates: ExecutionTemplate[] = [
  {
    id: "tpl-1",
    name: "demo-template",
    description: null,
    build_artifact_id: "art-1",
    artifact_type: "scrapy",
    project: "demo",
    version: "v1",
    command: "scrapy crawl phase1",
    node_strategy: "all",
    node_ids: [],
    created_at: "2026-06-19T00:00:00Z",
    updated_at: "2026-06-19T00:00:00Z",
  },
];

const sampleArtifacts: BuildArtifact[] = [
  {
    id: "art-1",
    artifact_type: "scrapy",
    package_format: "egg",
    name: "demo",
    filename: "demo.egg",
    content_hash: "sha-abc",
    size_bytes: 1024,
    project: "demo",
    version: "v1",
    spiders: ["phase1", "phase2"],
    fetch_path: "/api/v1/artifacts/art-1/egg",
    runnable: true,
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
  task_id: "task-9",
  status: "queued",
}));
const deleteTemplate = vi.fn(async (_id: string) => undefined);
const listBuildArtifacts = vi.fn(async () => sampleArtifacts);
const listNodes = vi.fn(async () => sampleNodes);

vi.mock("@/api/templates", () => ({
  listTemplates: () => listTemplates(),
  createTemplate: (payload: unknown) => createTemplate(payload),
  runTemplate: (id: string) => runTemplate(id),
  deleteTemplate: (id: string) => deleteTemplate(id),
}));
vi.mock("@/api/artifacts", () => ({
  listBuildArtifacts: () => listBuildArtifacts(),
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
    listBuildArtifacts.mockClear();
    listNodes.mockClear();
    push.mockClear();
  });

  it("renders fetched templates", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    expect(wrapper.text()).toContain(zh.templates.title);
    const vm = wrapper.vm as unknown as { templates: ExecutionTemplate[] };
    expect(vm.templates).toHaveLength(1);
  });

  it("submits a build_artifact_id + command payload", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: { name: string; buildArtifactId: string; command: string };
    };
    vm.openCreate();
    vm.form.name = "t2";
    vm.form.buildArtifactId = "art-1";
    vm.form.command = "scrapy crawl phase2 -s LOG_LEVEL=DEBUG";
    await vm.submitCreate();

    expect(createTemplate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "t2",
        build_artifact_id: "art-1",
        command: "scrapy crawl phase2 -s LOG_LEVEL=DEBUG",
      }),
    );
  });

  it("defaults the command from the artifact's first spider on open", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      form: { command: string };
    };
    vm.openCreate();
    expect(vm.form.command).toBe("scrapy crawl phase1");
  });

  it("blocks submit on an invalid command", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      openCreate: () => void;
      submitCreate: () => Promise<void>;
      form: { command: string };
      canSubmit: boolean;
      commandError: string;
    };
    vm.openCreate();
    vm.form.command = "scrapy crawl phase1; rm -rf /";
    await flushPromises();
    expect(vm.canSubmit).toBe(false);
    expect(vm.commandError).not.toBe("");
    await vm.submitCreate();
    expect(createTemplate).not.toHaveBeenCalled();
  });

  it("colors node tags via nodeTagType and renders no chips below the select", async () => {
    const wrapper = mount(TemplatesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      nodeTagType: (key: string) => string;
    };
    // healthy node -> success, offline -> danger, deleted -> info.
    expect(vm.nodeTagType("node-1")).toBe("success");
    expect(vm.nodeTagType("node-2")).toBe("danger");
    expect(vm.nodeTagType("node-3")).toBe("info");
    // the old duplicate chips-below block is gone.
    expect(wrapper.find(".node-chips").exists()).toBe(false);
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
      onRun: (t: ExecutionTemplate) => Promise<void>;
    };
    await vm.onRun(sampleTemplates[0]);
    expect(runTemplate).toHaveBeenCalledWith("tpl-1");
    expect(push).toHaveBeenCalledWith("/tasks/task-9");
  });
});
