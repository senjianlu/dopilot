import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { ExecutionSummary } from "@/api/types";

const sampleExecutions: ExecutionSummary[] = [
  {
    id: "exec-1",
    task_type: "scrapy",
    target: "demo",
    status: "running",
    node_strategy: "all",
    created_at: "2026-06-18T00:00:00Z",
    started_at: "2026-06-18T00:00:01Z",
    finished_at: null,
    attempt_count: 1,
  },
];

vi.mock("@/api/executions", () => ({
  listExecutions: vi.fn(async () => sampleExecutions),
}));

import ExecutionsPage from "@/pages/ExecutionsPage.vue";

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: "zh",
    fallbackLocale: "en",
    messages: { zh, en },
  });
}

describe("ExecutionsPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders fetched execution rows", async () => {
    const wrapper = mount(ExecutionsPage, {
      global: {
        plugins: [makeI18n()],
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
          "router-link": { template: "<a><slot /></a>" },
        },
      },
    });

    await flushPromises();

    expect(wrapper.text()).toContain(zh.executions.title);
    const vm = wrapper.vm as unknown as { executions: ExecutionSummary[] };
    expect(vm.executions).toHaveLength(1);
    expect(vm.executions[0].target).toBe("demo");
    expect(vm.executions[0].status).toBe("running");
  });
});
