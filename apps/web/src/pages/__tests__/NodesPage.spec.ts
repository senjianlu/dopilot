import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import type { NodeInfo } from "@/api/types";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";

const sampleNodes: NodeInfo[] = [
  {
    id: "n1",
    agent_id: "agent-alpha",
    endpoint: "http://10.0.0.1:6800",
    status: "healthy",
    capabilities: { scrapy: true, script: false, docker: false },
    last_seen_at: "2026-06-18T00:00:00Z",
  },
];

// Self-contained mock of the nodes API used by NodesPage.
vi.mock("@/api/nodes", () => ({
  listNodes: vi.fn(async () => sampleNodes),
  refreshNodes: vi.fn(async () => sampleNodes),
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

describe("NodesPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders fetched node endpoints and the Chinese refresh label", async () => {
    const wrapper = mount(NodesPage, {
      global: {
        plugins: [makeI18n()],
        // Stub Element Plus components so we do not need the full library.
        stubs: {
          "el-card": { template: "<div><slot name='header' /><slot /></div>" },
          "el-button": { template: "<button><slot /></button>" },
          "el-table": {
            props: ["data"],
            template: "<div class='el-table'><slot /></div>",
          },
          "el-table-column": {
            props: ["label", "prop"],
            template: "<div class='col'>{{ label }}</div>",
          },
          "el-tag": { template: "<span><slot /></span>" },
        },
      },
    });

    await flushPromises();

    // Chinese i18n label for nodes.refresh.
    expect(wrapper.text()).toContain(zh.nodes.refresh);
    // The fetched node endpoint is bound into the component data.
    const vm = wrapper.vm as unknown as { nodes: NodeInfo[] };
    expect(vm.nodes).toHaveLength(1);
    expect(vm.nodes[0].endpoint).toBe("http://10.0.0.1:6800");
  });
});
