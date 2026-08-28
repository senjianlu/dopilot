import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import { LogViewer } from "@/components/features/log-viewer";

const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (m: string) => toastError(m),
    success: (m: string) => toastSuccess(m),
  },
}));

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

// Real clipboard descriptor, restored after each test that swaps it out.
const clipboardDescriptor = Object.getOwnPropertyDescriptor(
  navigator,
  "clipboard",
);

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    value,
    configurable: true,
    writable: true,
  });
}

function restoreClipboard() {
  if (clipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  } else {
    // @ts-expect-error jsdom may not define it at all
    delete navigator.clipboard;
  }
}

/** Render the viewer and push one SSE chunk so the buffer is non-empty. */
async function renderWithContent(content = "hello world") {
  renderWithProviders(<LogViewer taskId="task-1" />);
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
  act(() => {
    MockEventSource.instances[0].emit("log", JSON.stringify({ content }));
  });
  await waitFor(() =>
    expect(screen.getByTestId("log-body")).toHaveTextContent(content),
  );
}

beforeEach(() => {
  MockEventSource.instances = [];
  toastError.mockReset();
  toastSuccess.mockReset();
  fetchStreamToken.mockReset();
  getToken.mockReset();
  getToken.mockReturnValue(null);
  // @ts-expect-error install the stand-in
  global.EventSource = MockEventSource;
});

afterEach(() => {
  restoreClipboard();
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
  it("copies the current buffer", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    await renderWithContent();

    await user.click(screen.getByTestId("log-copy"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("hello world"));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("disables copy when the buffer is empty", async () => {
    renderWithProviders(<LogViewer taskId="task-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("log-copy")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("log-copy")).toBeDisabled();
  });

  it("warns when clipboard is unavailable", async () => {
    const user = userEvent.setup();
    // http:// (non-secure context): navigator.clipboard does not exist at all.
    setClipboard(undefined);
    await renderWithContent();

    await user.click(screen.getByTestId("log-copy"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    // No crash: the viewer is still rendered.
    expect(screen.getByTestId("log-body")).toBeInTheDocument();
  });

  it("warns when clipboard write is rejected", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    setClipboard({ writeText });
    await renderWithContent();

    await user.click(screen.getByTestId("log-copy"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(screen.getByTestId("log-body")).toBeInTheDocument();
  });

  it("explains the copy scope", async () => {
    await renderWithContent();
    // The live stream only replays a tail, so the button must say that it
    // copies the CURRENT VIEW rather than the whole log.
    const button = screen.getByTestId("log-copy");
    expect(button).toHaveAccessibleDescription(/currently loaded in this view/i);
  });
});
