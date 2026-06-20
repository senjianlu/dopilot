import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { DailyTaskStatsResponse, HealthInfo } from "@/api/types";

const health: HealthInfo = {
  status: "ok",
  service: "dopilot-server",
  version: "0.1.0",
  database: "ok",
  postgresql: { status: "ok", version: "PostgreSQL 16" },
  redis: { status: "ok", version: "7.2" },
  nodes: { total: 2, online: 2, healthy: 1 },
  agent: { status: "yellow", schedulable: 2, healthy: 1 },
};

const stats: DailyTaskStatsResponse = {
  days: 30,
  timezone: "UTC",
  buckets: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-05-${String(i + 1).padStart(2, "0")}`,
    tasks: i === 29 ? 5 : 0,
    executions: i === 29 ? 8 : 0,
  })),
};

const getHealth = vi.fn(async () => health);
const getDailyTaskStats = vi.fn(async () => stats);

vi.mock("@/api/health", () => ({ getHealth: () => getHealth() }));
vi.mock("@/api/stats", () => ({ getDailyTaskStats: () => getDailyTaskStats() }));

import DashboardPage from "@/pages/DashboardPage.vue";

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
    "el-table": { props: ["data"], template: "<div class='el-table'><slot /></div>" },
    "el-table-column": {
      props: ["label", "prop"],
      template: "<div class='col'>{{ label }}</div>",
    },
  };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getHealth.mockClear();
    getDailyTaskStats.mockClear();
  });

  it("renders 4 service-health rows with lights + a daily chart", async () => {
    const wrapper = mount(DashboardPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();

    const vm = wrapper.vm as unknown as {
      serviceRows: { key: string; light: string }[];
      buckets: { tasks: number }[];
      hasActivity: boolean;
    };
    expect(vm.serviceRows.map((r) => r.key)).toEqual([
      "server",
      "agent",
      "redis",
      "postgresql",
    ]);
    // agent light reflects the server-computed scheduling status
    expect(vm.serviceRows.find((r) => r.key === "agent")?.light).toBe("yellow");
    // every row resolves to a breathing-light colour
    expect(
      vm.serviceRows.every((r) =>
        ["green", "yellow", "red", "gray"].includes(r.light),
      ),
    ).toBe(true);
    // chart has 30 buckets + activity -> svg rendered (outside the table stub)
    expect(vm.buckets).toHaveLength(30);
    expect(vm.hasActivity).toBe(true);
    expect(wrapper.find("svg.bar-chart").exists()).toBe(true);
  });
});