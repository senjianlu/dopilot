import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import type { RunExecutionRequest } from "@/api/types";

const runExecution = vi.fn(async (_payload: RunExecutionRequest) => ({
  execution_id: "exec-1",
  status: "queued",
}));
const push = vi.fn(async () => {});

vi.mock("@/api/executions", () => ({
  runExecution: (payload: RunExecutionRequest) => runExecution(payload),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push }),
}));

import ScrapyRunPage from "@/pages/ScrapyRunPage.vue";

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
    "el-form": { template: "<form><slot /></form>" },
    "el-form-item": { template: "<div><slot /></div>" },
    "el-input": {
      props: ["modelValue"],
      emits: ["update:modelValue"],
      template:
        "<input :value='modelValue' @input=\"$emit('update:modelValue', $event.target.value)\" />",
    },
    "el-select": {
      props: ["modelValue"],
      template: "<div><slot /></div>",
    },
    "el-option": { props: ["label", "value"], template: "<div />" },
    "el-button": {
      template: "<button @click=\"$emit('click')\"><slot /></button>",
    },
    "el-alert": { template: "<div><slot /></div>" },
  };
}

describe("ScrapyRunPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    runExecution.mockClear();
    push.mockClear();
  });

  it("submits the form and calls runExecution with the correct payload", async () => {
    const wrapper = mount(ScrapyRunPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });

    const vm = wrapper.vm as unknown as {
      form: { project: string; spider: string; version: string };
      args: { key: string; value: string }[];
      settings: { key: string; value: string }[];
      onSubmit: () => Promise<void>;
    };
    vm.form.project = "demo";
    vm.form.spider = "phase1";
    vm.form.version = "v1";
    vm.args[0].key = "limit";
    vm.args[0].value = "10";
    vm.settings[0].key = "LOG_LEVEL";
    vm.settings[0].value = "INFO";

    await vm.onSubmit();
    await flushPromises();

    expect(runExecution).toHaveBeenCalledTimes(1);
    const payload = runExecution.mock.calls[0][0];
    expect(payload).toEqual({
      task_type: "scrapy",
      target: "demo",
      node_strategy: "all",
      node_ids: [],
      params: {
        project: "demo",
        spider: "phase1",
        version: "v1",
        settings: { LOG_LEVEL: "INFO" },
        args: { limit: "10" },
      },
    });
    expect(push).toHaveBeenCalledWith({
      name: "execution-detail",
      params: { id: "exec-1" },
    });
  });
});
