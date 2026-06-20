import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import type { NodeInfo } from "@/api/types";
import { nodeBadge } from "@/utils/nodeBadge";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";

function makeNode(overrides: Partial<NodeInfo> = {}): NodeInfo {
  return {
    id: "n1",
    agent_id: "agent-alpha",
    endpoint: "http://10.0.0.1:6800",
    status: "healthy",
    capabilities: { scrapy: true, script: false, docker: false },
    health: { scrapyd: { running: true, port: 6801, pid: 42 } },
    last_seen_at: "2026-06-18T00:00:00Z",
    scheduling_enabled: true,
    scheduling_disabled_at: null,
    deleted_at: null,
    ...overrides,
  };
}

const listNodes = vi.fn(async () => [makeNode()]);
const offlineNode = vi.fn(async (_id: string) => makeNode({ scheduling_enabled: false }));
const onlineNode = vi.fn(async (_id: string) => makeNode());
const deleteNode = vi.fn(async (_id: string) =>
  makeNode({ deleted_at: "2026-06-20T00:00:00Z" }),
);

vi.mock("@/api/nodes", () => ({
  listNodes: () => listNodes(),
  refreshNodes: () => listNodes(),
  offlineNode: (id: string) => offlineNode(id),
  onlineNode: (id: string) => onlineNode(id),
  deleteNode: (id: string) => deleteNode(id),
}));

import NodesPage from "@/pages/NodesPage.vue";

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
    "el-tag": { template: "<span><slot /></span>" },
  };
}

describe("NodesPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listNodes.mockClear();
    offlineNode.mockClear();
    onlineNode.mockClear();
    deleteNode.mockClear();
  });

  it("refresh re-lists via the list endpoint (no /nodes/refresh)", async () => {
    const wrapper = mount(NodesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    expect(wrapper.text()).toContain(zh.nodes.refresh);
    const vm = wrapper.vm as unknown as { nodes: NodeInfo[] };
    expect(vm.nodes).toHaveLength(1);
    expect(vm.nodes[0].endpoint).toBe("http://10.0.0.1:6800");
    expect(listNodes).toHaveBeenCalled();
  });

  it("offline/online/delete call the matching endpoints and reload", async () => {
    const wrapper = mount(NodesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      onOffline: (n: NodeInfo) => Promise<void>;
      onOnline: (n: NodeInfo) => Promise<void>;
      onDelete: (n: NodeInfo) => Promise<void>;
    };
    await vm.onOffline(makeNode());
    expect(offlineNode).toHaveBeenCalledWith("n1");
    await vm.onOnline(makeNode({ scheduling_enabled: false }));
    expect(onlineNode).toHaveBeenCalledWith("n1");
    await vm.onDelete(makeNode());
    expect(deleteNode).toHaveBeenCalledWith("n1");
  });

  it("operation visibility honors id/scheduling/deleted state", async () => {
    const wrapper = mount(NodesPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      canOffline: (n: NodeInfo) => boolean;
      canOnline: (n: NodeInfo) => boolean;
      canDelete: (n: NodeInfo) => boolean;
    };
    // healthy online persisted node: can offline + delete, cannot online
    expect(vm.canOffline(makeNode())).toBe(true);
    expect(vm.canOnline(makeNode())).toBe(false);
    expect(vm.canDelete(makeNode())).toBe(true);
    // offline node: can online, cannot offline
    expect(vm.canOnline(makeNode({ scheduling_enabled: false }))).toBe(true);
    // configured-but-unseen (id == null): no ops
    expect(vm.canOffline(makeNode({ id: null }))).toBe(false);
    expect(vm.canDelete(makeNode({ id: null }))).toBe(false);
    // deleted node: no ops
    expect(vm.canDelete(makeNode({ deleted_at: "2026-06-20T00:00:00Z" }))).toBe(false);
  });
});

describe("nodeBadge precedence", () => {
  it("deleted > offline > healthy > warning", () => {
    expect(
      nodeBadge({ status: "healthy", scheduling_enabled: true, deleted_at: "x" }),
    ).toBe("deleted");
    expect(
      nodeBadge({ status: "healthy", scheduling_enabled: false, deleted_at: null }),
    ).toBe("offline");
    expect(
      nodeBadge({ status: "healthy", scheduling_enabled: true, deleted_at: null }),
    ).toBe("healthy");
    expect(
      nodeBadge({ status: "degraded", scheduling_enabled: true, deleted_at: null }),
    ).toBe("warning");
    expect(
      nodeBadge({ status: "unhealthy", scheduling_enabled: true, deleted_at: null }),
    ).toBe("warning");
  });
});