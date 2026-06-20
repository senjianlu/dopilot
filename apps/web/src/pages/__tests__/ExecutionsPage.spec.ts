import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { ExecutionsResponse, ListExecutionsParams } from "@/api/types";

function makeResponse(): ExecutionsResponse {
  return {
    executions: [
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
    ],
    page: 1,
    page_size: 20,
    total: 42,
    spiders: ["alpha", "beta"],
  };
}

const listExecutions = vi.fn(async (_params?: ListExecutionsParams) => makeResponse());

vi.mock("@/api/executions", () => ({
  listExecutions: (params?: ListExecutionsParams) => listExecutions(params),
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

function makeStubs() {
  return {
    "el-card": { template: "<div><slot name='header' /><slot /></div>" },
    "el-button": { template: "<button @click=\"$emit('click')\"><slot /></button>" },
    "el-table": { props: ["data"], template: "<div class='el-table'><slot /></div>" },
    "el-table-column": {
      props: ["label", "prop"],
      template: "<div class='col'>{{ label }}</div>",
    },
    "el-tag": { template: "<span><slot /></span>" },
    "el-select": { template: "<select><slot /></select>" },
    "el-option": { template: "<option><slot /></option>" },
    "el-pagination": { template: "<div class='pager' />" },
    "router-link": { template: "<a><slot /></a>" },
  };
}

describe("ExecutionsPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listExecutions.mockClear();
  });

  it("requests a backend page and renders rows + total", async () => {
    const wrapper = mount(ExecutionsPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    expect(wrapper.text()).toContain(zh.executions.title);
    const vm = wrapper.vm as unknown as {
      executions: { target: string }[];
      total: number;
      spiders: string[];
    };
    expect(vm.executions).toHaveLength(1);
    expect(vm.total).toBe(42);
    expect(vm.spiders).toEqual(["alpha", "beta"]);
    // first load passes pagination params
    expect(listExecutions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1 }),
    );
  });

  it("sends spider + pagination params on filter/page/size changes", async () => {
    const wrapper = mount(ExecutionsPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      spider: string;
      onSpiderChange: () => void;
      onPageChange: (n: number) => void;
      onSizeChange: (n: number) => void;
    };

    vm.spider = "alpha";
    vm.onSpiderChange();
    await flushPromises();
    expect(listExecutions).toHaveBeenLastCalledWith(
      expect.objectContaining({ spider: "alpha", page: 1 }),
    );

    vm.onPageChange(2);
    await flushPromises();
    expect(listExecutions).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, spider: "alpha" }),
    );

    vm.onSizeChange(50);
    await flushPromises();
    expect(listExecutions).toHaveBeenLastCalledWith(
      expect.objectContaining({ pageSize: 50, page: 1 }),
    );
  });
});