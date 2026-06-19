import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";
import { useAuthStore } from "@/stores/auth";

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

const mocks = vi.hoisted(() => ({
  fetchStreamToken: vi.fn(async () => ({
    stream_token: "tok",
    expires_at: null,
  })),
}));

vi.mock("@/api/executions", () => ({
  buildStreamUrl: (
    id: string,
    query: { streamToken?: string } = {},
  ) => {
    const params = new URLSearchParams();
    if (query.streamToken) {
      params.set("stream_token", query.streamToken);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return `/api/v1/executions/${id}/logs/stream${suffix}`;
  },
  fetchStreamToken: mocks.fetchStreamToken,
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
    mocks.fetchStreamToken.mockClear();
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

  it("uses a stream token when a bearer token exists", async () => {
    const auth = useAuthStore();
    auth.token = "bearer-token";

    mount(LogViewer, {
      props: { executionId: "exec-1" },
      global: {
        plugins: [makeI18n()],
        stubs: {
          "el-tag": { template: "<span><slot /></span>" },
        },
      },
    });

    await flushPromises();

    expect(mocks.fetchStreamToken).toHaveBeenCalledWith("exec-1");
    expect(FakeEventSource.instances[0].url).toContain("stream_token=tok");
  });
});
