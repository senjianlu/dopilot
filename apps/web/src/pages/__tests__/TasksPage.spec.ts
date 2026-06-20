import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { ListTasksParams, TasksResponse } from "@/api/types";

function makeResponse(): TasksResponse {
  return {
    tasks: [
      {
        id: "task-1",
        artifact_type: "scrapy",
        target: "demo",
        status: "running",
        node_strategy: "all",
        created_at: "2026-06-18T00:00:00Z",
        started_at: "2026-06-18T00:00:01Z",
        finished_at: null,
        execution_count: 1,
      },
    ],
    page: 1,
    page_size: 20,
    total: 42,
    spiders: ["alpha", "beta"],
  };
}

const listTasks = vi.fn(async (_params?: ListTasksParams) => makeResponse());

vi.mock("@/api/tasks", () => ({
  listTasks: (params?: ListTasksParams) => listTasks(params),
}));

import TasksPage from "@/pages/TasksPage.vue";

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

describe("TasksPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listTasks.mockClear();
  });

  it("requests a backend page and renders rows + total", async () => {
    const wrapper = mount(TasksPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    expect(wrapper.text()).toContain(zh.tasks.title);
    const vm = wrapper.vm as unknown as {
      tasks: { target: string; execution_count: number }[];
      total: number;
      spiders: string[];
    };
    expect(vm.tasks).toHaveLength(1);
    expect(vm.tasks[0].execution_count).toBe(1);
    expect(vm.total).toBe(42);
    expect(vm.spiders).toEqual(["alpha", "beta"]);
    // first load passes pagination params
    expect(listTasks).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1 }),
    );
  });

  it("sends spider + pagination params on filter/page/size changes", async () => {
    const wrapper = mount(TasksPage, {
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
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ spider: "alpha", page: 1 }),
    );

    vm.onPageChange(2);
    await flushPromises();
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, spider: "alpha" }),
    );

    vm.onSizeChange(50);
    await flushPromises();
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ pageSize: 50, page: 1 }),
    );
  });
});
