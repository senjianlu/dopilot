import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/lib/test/render";
import { LogViewer } from "@/components/features/log-viewer";

const fetchStreamToken = vi.fn();
vi.mock("@/lib/api/tasks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/tasks")>();
  return {
    ...actual,
    fetchStreamToken: (id: string) => fetchStreamToken(id),
  };
});

const getToken = vi.fn<() => string | null>(() => null);
vi.mock("@/lib/api/token", () => ({
  getToken: () => getToken(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
}));

// Minimal EventSource stand-in so jsdom can exercise the SSE wiring.
class MockEventSource {
  static instances: MockEventSource[] = [];
  static CLOSED = 2;
  CLOSED = 2;
  url: string;
  readyState = 0;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  close() {
    this.readyState = 2;
  }
  emit(type: string, data?: string) {
    (this.listeners[type] ?? []).forEach((cb) =>
      cb({ data } as MessageEvent),
    );
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  fetchStreamToken.mockReset();
  getToken.mockReset();
  getToken.mockReturnValue(null);
  // @ts-expect-error install the stand-in
  global.EventSource = MockEventSource;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LogViewer", () => {
  it("appends streamed log content and shows the complete badge", async () => {
    renderWithProviders(<LogViewer taskId="task-1" />);

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const es = MockEventSource.instances[0];
    // No token -> no stream-token fetch and no token query param.
    expect(fetchStreamToken).not.toHaveBeenCalled();
    expect(es.url).toContain("/api/v1/tasks/task-1/logs/stream");
    expect(es.url).not.toContain("stream_token");

    // The SSE handlers call setState, so emits must run inside act(...).
    act(() => {
      es.emit("log", JSON.stringify({ content: "hello " }));
      es.emit("log", JSON.stringify({ content: "world" }));
    });
    await waitFor(() =>
      expect(screen.getByTestId("log-body")).toHaveTextContent("hello world"),
    );

    act(() => {
      es.emit("complete");
    });
    await waitFor(() =>
      expect(screen.getByText("Complete")).toBeInTheDocument(),
    );
  });

  it("passes execution_id into the stream URL when given", async () => {
    renderWithProviders(<LogViewer taskId="task-1" executionId="ex-2" />);

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(MockEventSource.instances[0].url).toContain("execution_id=ex-2");
  });

  it("fetches a short-lived stream token when web auth is on", async () => {
    getToken.mockReturnValue("bearer-tok");
    fetchStreamToken.mockResolvedValue({
      stream_token: "stream-xyz",
      expires_at: null,
    });

    renderWithProviders(<LogViewer taskId="task-9" />);

    await waitFor(() => expect(fetchStreamToken).toHaveBeenCalledWith("task-9"));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(MockEventSource.instances[0].url).toContain("stream_token=stream-xyz");
  });
});
