import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type { ResourceStatsResponse } from "@/lib/api/types";

const getResourceStats = vi.fn();
const sweepNow = vi.fn();
const rewriteAof = vi.fn();
const terminalCleanup = vi.fn();
vi.mock("@/lib/api/maintenance", () => ({
  getResourceStats: () => getResourceStats(),
  sweepNow: () => sweepNow(),
  rewriteAof: () => rewriteAof(),
  terminalCleanup: (body: unknown) => terminalCleanup(body),
}));

import MaintenancePage from "@/app/(app)/maintenance/page";

function makeStats(
  overrides: Partial<ResourceStatsResponse> = {},
): ResourceStatsResponse {
  return {
    sampled_at: "2026-07-24T12:00:00Z",
    sweep_enabled: true,
    scopes: [
      {
        scope: "server",
        status: "ok",
        sampled_at: "2026-07-24T12:00:00Z",
        last_seen_at: null,
        entries: [
          { key: "server.logs_bytes", kind: "bytes", value: 1024, limit: null, level: "ok" },
          {
            key: "server.artifacts_bytes",
            kind: "bytes",
            value: 900,
            limit: 1000,
            level: "critical",
          },
          {
            key: "server.max_log_file_bytes",
            kind: "bytes",
            value: null,
            limit: 100,
            level: "unknown",
          },
        ],
      },
      {
        scope: "redis",
        status: "unavailable",
        sampled_at: null,
        last_seen_at: null,
        entries: [],
      },
      {
        scope: "agent:a1",
        status: "stale",
        sampled_at: "2026-07-24T10:00:00Z",
        last_seen_at: "2026-07-24T11:59:00Z",
        entries: [
          { key: "agent.cache_bytes", kind: "bytes", value: 700, limit: 1000, level: "warn" },
        ],
      },
      {
        scope: "agent:a2",
        status: "unavailable",
        sampled_at: null,
        last_seen_at: "2026-07-24T09:00:00Z",
        entries: [],
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  getResourceStats.mockReset().mockResolvedValue(makeStats());
  sweepNow.mockReset().mockResolvedValue({
    steps: {
      cleanup: { status: "ok" },
      event_audit: { status: "ok", pruned: 3 },
      stream_trim: { status: "skipped" },
    },
  });
  rewriteAof.mockReset().mockResolvedValue({ started: true });
  terminalCleanup.mockReset().mockResolvedValue({
    dry_run: true,
    cutoff: "2026-06-24T00:00:00Z",
    tasks: 2,
    executions: 3,
    log_files: 1,
    log_files_removed: 0,
    log_bytes: 4096,
    command_outbox: 0,
  });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("MaintenancePage — dashboard", () => {
  it("renders scopes, level tones, null-limit and scope statuses", async () => {
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("resource-scope-server")).toBeInTheDocument(),
    );
    // level -> data-tone mapping (all four levels)
    expect(
      screen.getByTestId("resource-level-server.logs_bytes"),
    ).toHaveAttribute("data-tone", "green");
    expect(
      screen.getByTestId("resource-level-server.artifacts_bytes"),
    ).toHaveAttribute("data-tone", "red");
    expect(
      screen.getByTestId("resource-level-server.max_log_file_bytes"),
    ).toHaveAttribute("data-tone", "gray");
    expect(
      screen.getByTestId("resource-level-agent.cache_bytes"),
    ).toHaveAttribute("data-tone", "amber");
    // null-limit renders "—"
    const logRow = screen.getByTestId("resource-entry-server.logs_bytes");
    expect(within(logRow).getByText("—")).toBeInTheDocument();
    // scope statuses: stale (amber) + unavailable (gray)
    expect(
      screen.getByTestId("resource-scope-status-agent:a1"),
    ).toHaveAttribute("data-tone", "amber");
    expect(
      screen.getByTestId("resource-scope-status-redis"),
    ).toHaveAttribute("data-tone", "gray");
    // stale scope shows its sample time; unavailable agent shows last_seen_at
    expect(
      screen.getByTestId("resource-scope-sampled-agent:a1"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("resource-scope-lastseen-agent:a2"),
    ).toBeInTheDocument();
    // sampled-at is shown
    expect(screen.getByTestId("maintenance-sampled-at")).toBeInTheDocument();
  });

  it("shows a first-sample skeleton when sampled_at is null", async () => {
    getResourceStats.mockResolvedValue(
      makeStats({ sampled_at: null, scopes: [] }),
    );
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-first-sample")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("resource-scope-server")).not.toBeInTheDocument();
  });
});

describe("MaintenancePage — actions", () => {
  it("runs sweep-now only after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-sweep")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-sweep"));
    await user.click(await screen.findByTestId("confirm-accept"));
    await waitFor(() => expect(sweepNow).toHaveBeenCalledOnce());
    expect(
      await screen.findByTestId("maintenance-sweep-result"),
    ).toBeInTheDocument();
  });

  it("does not sweep when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-sweep")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-sweep"));
    await user.click(await screen.findByTestId("confirm-cancel"));
    expect(sweepNow).not.toHaveBeenCalled();
  });

  it("rewrites AOF after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-rewrite-aof")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-rewrite-aof"));
    await user.click(await screen.findByTestId("confirm-accept"));
    await waitFor(() => expect(rewriteAof).toHaveBeenCalledOnce());
  });

  it("does not rewrite AOF when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-rewrite-aof")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-rewrite-aof"));
    await user.click(await screen.findByTestId("confirm-cancel"));
    expect(rewriteAof).not.toHaveBeenCalled();
  });

  it("previews terminal cleanup (dry run) and renders the summary", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-preview")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-preview"));
    await waitFor(() => expect(terminalCleanup).toHaveBeenCalledOnce());
    expect(terminalCleanup).toHaveBeenCalledWith(
      expect.objectContaining({ dry_run: true }),
    );
    expect(
      await screen.findByTestId("maintenance-summary"),
    ).toBeInTheDocument();
  });

  it("executes terminal cleanup (destructive) only after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-run")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-run"));
    await user.click(await screen.findByTestId("confirm-accept"));
    await waitFor(() => expect(terminalCleanup).toHaveBeenCalledOnce());
    expect(terminalCleanup).toHaveBeenCalledWith(
      expect.objectContaining({ dry_run: false }),
    );
  });

  it("does not execute terminal cleanup when cancelled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MaintenancePage />);
    await waitFor(() =>
      expect(screen.getByTestId("maintenance-run")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("maintenance-run"));
    await user.click(await screen.findByTestId("confirm-cancel"));
    expect(terminalCleanup).not.toHaveBeenCalled();
  });
});

describe("MaintenancePage — polling", () => {
  it("polls every 10s and stops after unmount", async () => {
    vi.useFakeTimers();
    const { unmount } = renderWithProviders(<MaintenancePage />);
    // initial fetch
    await vi.waitFor(() => expect(getResourceStats).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(getResourceStats).toHaveBeenCalledTimes(2);
    unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(getResourceStats).toHaveBeenCalledTimes(2); // no polling after unmount
  });
});
