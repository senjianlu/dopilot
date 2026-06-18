import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";

// Fake EventSource capturing listeners so the test can drive events manually.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CLOSED = 2;
  url: string;
  readyState = 0;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: (e: MessageEvent) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }

  emit(type: string, data?: unknown): void {
    for (const cb of this.listeners[type] ?? []) {
      cb({ data: data == null ? "" : JSON.stringify(data) } as MessageEvent);
    }
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
}

vi.stubGlobal("EventSource", FakeEventSource);

// Auth off by default -> no stream token fetch.
vi.mock("@/api/executions", () => ({
  buildStreamUrl: (id: string) => `/api/v1/executions/${id}/logs/stream`,
  fetchStreamToken: vi.fn(async () => ({
    stream_token: "tok",
    expires_at: null,
  })),
}));

import LogViewer from "@/components/LogViewer.vue";

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: "zh",
    fallbackLocale: "en",
    messages: { zh, en },
  });
}

describe("LogViewer", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    FakeEventSource.instances = [];
  });

  it("appends incremental log data and shows complete", async () => {
    const wrapper = mount(LogViewer, {
      props: { executionId: "exec-1" },
      global: {
        plugins: [makeI18n()],
        stubs: {
          "el-tag": { template: "<span><slot /></span>" },
        },
      },
    });

    await flushPromises();

    expect(FakeEventSource.instances).toHaveLength(1);
    const es = FakeEventSource.instances[0];

    es.emit("log", { start_offset: 0, end_offset: 5, content: "hello" });
    es.emit("log", { start_offset: 5, end_offset: 11, content: " world" });
    await flushPromises();

    expect(wrapper.text()).toContain("hello world");

    es.emit("complete", { status: "complete" });
    await flushPromises();

    expect(wrapper.text()).toContain(zh.logs.complete);
    expect(es.readyState).toBe(FakeEventSource.CLOSED);
  });
});
