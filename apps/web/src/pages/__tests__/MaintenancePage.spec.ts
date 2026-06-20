import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import type { TerminalCleanupResponse } from "@/api/types";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";

const summary: TerminalCleanupResponse = {
  dry_run: true,
  cutoff: "2026-05-21T00:00:00+00:00",
  tasks: 3,
  executions: 5,
  log_files: 5,
  log_files_removed: 0,
  log_bytes: 2097152,
  command_outbox: 4,
};

const terminalCleanup = vi.fn(async (body: { dry_run?: boolean }) => ({
  ...summary,
  dry_run: !!body.dry_run,
  log_files_removed: body.dry_run ? 0 : 5,
}));

vi.mock("@/api/maintenance", () => ({
  terminalCleanup: (body: unknown) => terminalCleanup(body as { dry_run?: boolean }),
}));

const confirmAction = vi.fn(async () => true);
vi.mock("@/utils/confirm", () => ({
  confirmAction: () => confirmAction(),
}));

import MaintenancePage from "@/pages/MaintenancePage.vue";

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
    "el-card": {
      props: ["shadow"],
      template: "<div><slot name='header' /><slot /></div>",
    },
    "el-button": {
      template: "<button @click=\"$emit('click')\"><slot /></button>",
    },
    "el-form": { template: "<form><slot /></form>" },
    "el-form-item": { props: ["label"], template: "<div>{{ label }}<slot /></div>" },
    "el-input-number": { props: ["modelValue"], template: "<input type='number' />" },
    "el-alert": { props: ["title"], template: "<div>{{ title }}</div>" },
    "el-descriptions": { template: "<div><slot /></div>" },
    "el-descriptions-item": {
      props: ["label"],
      template: "<div>{{ label }}<slot /></div>",
    },
    "el-tag": { template: "<span><slot /></span>" },
  };
}

describe("MaintenancePage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    terminalCleanup.mockClear();
    confirmAction.mockClear();
    confirmAction.mockResolvedValue(true);
  });

  it("previews (dry run) without confirmation", async () => {
    const wrapper = mount(MaintenancePage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    const vm = wrapper.vm as unknown as {
      run: (dryRun: boolean) => Promise<void>;
      summary: TerminalCleanupResponse | null;
    };
    await vm.run(true);
    await flushPromises();
    expect(confirmAction).not.toHaveBeenCalled();
    expect(terminalCleanup).toHaveBeenCalledWith({
      older_than_days: 30,
      dry_run: true,
    });
    expect(vm.summary?.dry_run).toBe(true);
    expect(vm.summary?.tasks).toBe(3);
  });

  it("runs the real cleanup only after confirmation", async () => {
    const wrapper = mount(MaintenancePage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    const vm = wrapper.vm as unknown as {
      run: (dryRun: boolean) => Promise<void>;
      summary: TerminalCleanupResponse | null;
    };
    await vm.run(false);
    await flushPromises();
    expect(confirmAction).toHaveBeenCalledTimes(1);
    expect(terminalCleanup).toHaveBeenCalledWith({
      older_than_days: 30,
      dry_run: false,
    });
    expect(vm.summary?.dry_run).toBe(false);
    expect(vm.summary?.log_files_removed).toBe(5);
  });

  it("does NOT run cleanup when confirmation is declined", async () => {
    confirmAction.mockResolvedValue(false);
    const wrapper = mount(MaintenancePage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    const vm = wrapper.vm as unknown as {
      run: (dryRun: boolean) => Promise<void>;
    };
    await vm.run(false);
    await flushPromises();
    expect(terminalCleanup).not.toHaveBeenCalled();
  });
});
