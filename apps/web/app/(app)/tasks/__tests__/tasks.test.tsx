import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type {
  BuildArtifactOption,
  TaskSummary,
  TasksResponse,
} from "@/lib/api/types";

// The page reads its schedule drill-down filter from the URL, so the search
// params are swappable per test (reset to empty in beforeEach).
let searchParams = new URLSearchParams();
const routerReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: routerReplace }),
  usePathname: () => "/tasks",
  useSearchParams: () => searchParams,
}));

const listTasks = vi.fn();
vi.mock("@/lib/api/tasks", () => ({
  listTasks: (params: unknown) => listTasks(params),
}));

const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: (m: string) => toastError(m), success: vi.fn() },
}));

import TasksPage from "@/app/(app)/tasks/page";

const scrapyArtifact: BuildArtifactOption = {
  id: "art-scrapy",
  name: "demo",
  artifact_type: "scrapy",
  version: "v1",
  distribution: null,
  project: "demo",
  label: "demo (v1)",
};

const wheelArtifact: BuildArtifactOption = {
  id: "art-wheel",
  name: "wheelpkg",
  artifact_type: "python_wheel",
  version: "1.0.0",
  distribution: "wheelpkg",
  project: null,
  label: "wheelpkg (1.0.0)",
};

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: "task-1",
    artifact_type: "scrapy",
    target: "demo:alpha",
    spider: "alpha",
    build_artifact: scrapyArtifact,
    status: "complete",
    node_strategy: "all",
    created_at: "2026-06-19T00:00:00Z",
    started_at: null,
    finished_at: null,
    execution_count: 1,
    ...overrides,
  };
}

function makeResponse(overrides: Partial<TasksResponse> = {}): TasksResponse {
  return {
    tasks: [makeTask()],
    page: 1,
    page_size: 20,
    total: 1,
    build_artifacts: [scrapyArtifact, wheelArtifact],
    ...overrides,
  };
}

beforeEach(() => {
  searchParams = new URLSearchParams();
  routerReplace.mockReset();
  toastError.mockReset();
  listTasks.mockReset().mockResolvedValue(makeResponse());
});

afterEach(() => {
  // A test that times out never reaches its own finally, so restoring the
  // clock here keeps fake timers from leaking into the next test.
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("TasksPage build-artifact filter", () => {
  it("shows the build artifact label in the table column (not the spider)", async () => {
    renderWithProviders(<TasksPage />);
    const cell = await screen.findByTestId("task-build-artifact-task-1");
    expect(cell).toHaveTextContent("demo (v1)");
    // the spider is no longer used as the build-artifact column.
    expect(cell).not.toHaveTextContent("alpha");
  });

  it("selecting a build artifact calls listTasks with buildArtifactId", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    // The first load is the "all" view (no build artifact filter).
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ buildArtifactId: null }),
    );

    await user.click(screen.getByTestId("tasks-build-filter"));
    const option = await screen.findByRole("option", {
      name: "wheelpkg (1.0.0)",
    });
    await user.click(option);

    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ buildArtifactId: "art-wheel" }),
      ),
    );
  });

  it("offers a distinct build-artifact option per known artifact", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");
    await user.click(screen.getByTestId("tasks-build-filter"));
    const listbox = await screen.findByRole("listbox");
    expect(
      within(listbox).getByRole("option", { name: "demo (v1)" }),
    ).toBeInTheDocument();
    expect(
      within(listbox).getByRole("option", { name: "wheelpkg (1.0.0)" }),
    ).toBeInTheDocument();
  });
});

describe("TasksPage status filter", () => {
  it("sends status null on the first load (all statuses)", async () => {
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: null }),
    );
  });

  it("selecting a status calls listTasks with status and resets to page 1", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    await user.click(screen.getByTestId("tasks-status-filter"));
    const option = await screen.findByRole("option", { name: "running" });
    await user.click(option);

    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 1, status: "running" }),
      ),
    );
  });

  it("preserves status across refresh, pagination, and page-size changes", async () => {
    const user = userEvent.setup();
    // Two pages so the next button is enabled.
    listTasks.mockResolvedValue(makeResponse({ total: 40 }));
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    await user.click(screen.getByTestId("tasks-status-filter"));
    await user.click(await screen.findByRole("option", { name: "failed" }));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed" }),
      ),
    );

    // Refresh keeps the status filter.
    await user.click(screen.getByText("Refresh"));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed" }),
      ),
    );

    // Next page keeps the status filter.
    await user.click(screen.getByTestId("tasks-next"));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2, status: "failed" }),
      ),
    );

    // Page-size change keeps the status filter and resets to page 1.
    await user.click(screen.getByTestId("tasks-page-size"));
    await user.click(await screen.findByRole("option", { name: "50 / Per page" }));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 1, pageSize: 50, status: "failed" }),
      ),
    );
  });
});

// A promise whose settlement this test controls, used to force out-of-order
// responses. Vitest has no built-in deferred, so build one.
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("TasksPage schedule drill-down", () => {
  it("reads schedule_id from the URL and shows a clearable chip", async () => {
    // TC-09
    const user = userEvent.setup();
    searchParams = new URLSearchParams(
      "schedule_id=sch-a&schedule_name=nightly",
    );
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ scheduleId: "sch-a" }),
    );
    expect(screen.getByTestId("tasks-schedule-filter")).toHaveTextContent(
      "nightly",
    );

    await user.click(screen.getByTestId("tasks-schedule-filter-clear"));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ scheduleId: null, page: 1 }),
      ),
    );
    expect(screen.queryByTestId("tasks-schedule-filter")).toBeNull();
    // The query string is dropped too, so a reload does not resurrect it.
    expect(routerReplace).toHaveBeenCalledWith("/tasks");
  });

  it("falls back to the schedule id when no name is in the URL", async () => {
    // TC-09 (fallback branch)
    searchParams = new URLSearchParams("schedule_id=sch-b");
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");
    expect(screen.getByTestId("tasks-schedule-filter")).toHaveTextContent(
      "sch-b",
    );
  });

  it("sends scheduleId null when the URL carries no schedule", async () => {
    // TC-09 (default branch)
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ scheduleId: null }),
    );
    expect(screen.queryByTestId("tasks-schedule-filter")).toBeNull();
  });
});

describe("TasksPage target search", () => {
  it("debounces typing and resets to page 1", async () => {
    // TC-10. Mount under real timers (React needs real macrotasks to flush the
    // initial request), then switch to a fake clock for the boundary itself.
    // The advances run inside a SYNCHRONOUS act() so React flushes the effect
    // without awaiting anything — awaiting under a fake clock deadlocks,
    // because vi.waitFor only pumps fake timers and React's scheduler needs a
    // real macrotask.
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");
    const callsBefore = listTasks.mock.calls.length;

    vi.useFakeTimers();
    try {
      fireEvent.change(screen.getByTestId("tasks-target-search"), {
        target: { value: "alpha" },
      });
      // Typing alone issues nothing.
      expect(listTasks.mock.calls.length).toBe(callsBefore);

      // One millisecond short of the window: still nothing on the wire.
      act(() => {
        vi.advanceTimersByTime(299);
      });
      expect(listTasks.mock.calls.length).toBe(callsBefore);

      // Crossing 300ms commits the term and issues exactly one request.
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(listTasks.mock.calls.length).toBe(callsBefore + 1);
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "alpha", page: 1 }),
      );
    } finally {
      vi.useRealTimers();
    }

    // Let the in-flight response settle under real timers so the state update
    // does not land outside act.
    await waitFor(() =>
      expect(screen.getByTestId("task-build-artifact-task-1")).toBeTruthy(),
    );
  });

  it("searches immediately on Enter and does not fire again after the delay", async () => {
    // TC-10 (Enter branch)
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    const input = screen.getByTestId("tasks-target-search");
    await user.type(input, "beta");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "beta", page: 1 }),
      ),
    );
    const callsAfterEnter = listTasks.mock.calls.length;

    // Past the debounce window: the pending timer must not fire a duplicate.
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(listTasks.mock.calls.length).toBe(callsAfterEnter);
  });

  it("uses the LATEST filters when the debounce fires, not the ones captured while typing", async () => {
    // TC-14: the regression plan review R-01 flagged — a pending debounce
    // callback must not resurrect the filter values that were current when the
    // keystroke happened. Both other filters (status dropdown and the schedule
    // chip) are changed INSIDE the 300ms window, then the clock is advanced
    // past it; the resulting request must carry all three latest values.
    searchParams = new URLSearchParams(
      "schedule_id=sch-a&schedule_name=nightly",
    );
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");
    expect(listTasks).toHaveBeenLastCalledWith(
      expect.objectContaining({ scheduleId: "sch-a", status: null }),
    );

    // FREEZE the clock BEFORE typing, so the debounce timer is a fake one we
    // control. (Installing the fake clock afterwards would leave the already
    // scheduled real timer untouched.) The dropdown interaction below burns far
    // more than 300ms of real time, which would otherwise let the debounce fire
    // before the other filters change and defeat the whole point.
    vi.useFakeTimers();
    try {
      fireEvent.change(screen.getByTestId("tasks-target-search"), {
        target: { value: "alpha" },
      });

      // Still inside the (now frozen) window: change status, clear the chip.
      // Driven with synchronous fireEvent — user-event awaits real macrotasks
      // that a fake clock never delivers, so it deadlocks here.
      fireEvent.keyDown(screen.getByTestId("tasks-status-filter"), {
        key: "ArrowDown",
      });
      act(() => {
        vi.advanceTimersByTime(1); // let Radix's own timers settle (still < 300)
      });
      fireEvent.click(screen.getByRole("option", { name: "failed" }));
      act(() => {
        vi.advanceTimersByTime(1);
      });
      fireEvent.click(screen.getByTestId("tasks-schedule-filter-clear"));
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", scheduleId: null }),
      );
      const callsBeforeDebounce = listTasks.mock.calls.length;

      // Now let the pending debounce fire. A stale-snapshot implementation
      // would issue status "__all__"/scheduleId "sch-a" here and, holding a
      // newer request id, would overwrite the correct result.
      act(() => {
        vi.advanceTimersByTime(400); // now cross the debounce window
      });
      expect(listTasks.mock.calls.length).toBe(callsBeforeDebounce + 1);
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "alpha",
          status: "failed",
          scheduleId: null,
          page: 1,
        }),
      );
    } finally {
      vi.useRealTimers();
    }

    // Let the in-flight response settle under real timers, so its state update
    // does not land outside act (which shows up as a warning in the log).
    await waitFor(() =>
      expect(screen.getByTestId("task-build-artifact-task-1")).toBeTruthy(),
    );

    // Stronger form: once a filter moved on, no later request may regress to
    // its previous value. Each filter is measured from its OWN change point —
    // the status changed one request before the chip was cleared.
    const params = listTasks.mock.calls.map(
      ([p]) => p as { status: unknown; scheduleId: unknown },
    );
    const firstFailed = params.findIndex((p) => p.status === "failed");
    expect(firstFailed).toBeGreaterThanOrEqual(0);
    for (const p of params.slice(firstFailed)) {
      expect(p.status).toBe("failed");
    }
    const firstCleared = params.findIndex((p) => p.scheduleId === null);
    expect(firstCleared).toBeGreaterThan(firstFailed);
    for (const p of params.slice(firstCleared)) {
      expect(p.scheduleId).toBeNull();
    }
  });

  it("discards a stale response that lands after a newer one", async () => {
    // TC-11: responses can arrive out of order; the older one must not win.
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    const first = deferred<TasksResponse>();
    const second = deferred<TasksResponse>();
    listTasks.mockReturnValueOnce(first.promise);
    listTasks.mockReturnValueOnce(second.promise);

    // Request A, then request B.
    await user.click(screen.getByTestId("tasks-status-filter"));
    await user.click(await screen.findByRole("option", { name: "running" }));
    await waitFor(() => expect(listTasks.mock.calls.length).toBeGreaterThan(1));

    await user.click(screen.getByTestId("tasks-status-filter"));
    await user.click(await screen.findByRole("option", { name: "failed" }));
    await waitFor(() => expect(listTasks.mock.calls.length).toBeGreaterThan(2));

    // B settles first and is rendered.
    second.resolve(
      makeResponse({
        tasks: [makeTask({ id: "task-new", target: "newer" })],
        total: 7,
      }),
    );
    await screen.findByTestId("task-build-artifact-task-new");
    const pagesForB = screen.getByTestId("tasks-page-indicator").textContent;

    // Now the stale A lands. Its payload differs in BOTH the rows and the
    // total, so applying it would be visible twice over.
    first.resolve(
      makeResponse({
        tasks: [makeTask({ id: "task-old", target: "older" })],
        total: 999,
      }),
    );
    // Await the stale promise itself (plus a second tick for the .then/.catch/
    // .finally chain the component attached to it) inside act, so React has
    // definitively processed everything before the assertions run. Without
    // this the checks below could pass merely because nothing had happened yet.
    await act(async () => {
      await first.promise;
      await Promise.resolve();
    });

    expect(screen.queryByTestId("task-build-artifact-task-old")).toBeNull();
    expect(screen.getByTestId("task-build-artifact-task-new")).toBeTruthy();
    // The page count still reflects B's total (7), not the stale 999.
    expect(screen.getByTestId("tasks-page-indicator").textContent).toBe(
      pagesForB,
    );
  });

  it("caps the search input so the UI cannot build a request the backend rejects", async () => {
    // TC-12 (boundary)
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    const input = screen.getByTestId("tasks-target-search") as HTMLInputElement;
    expect(input.maxLength).toBe(100);

    await user.click(input);
    await user.paste("z".repeat(120));
    expect(input.value.length).toBe(100);

    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "z".repeat(100) }),
      ),
    );
  });

  it("surfaces a toast instead of an unhandled rejection when the list fails", async () => {
    // TC-12 (failure branch)
    listTasks.mockReset().mockRejectedValue(new Error("boom"));
    renderWithProviders(<TasksPage />);
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("preserves the search term and schedule filter across paging and refresh", async () => {
    // TC-13
    const user = userEvent.setup();
    searchParams = new URLSearchParams("schedule_id=sch-a");
    listTasks.mockResolvedValue(makeResponse({ total: 40 }));
    renderWithProviders(<TasksPage />);
    await screen.findByTestId("task-build-artifact-task-1");

    await user.type(screen.getByTestId("tasks-target-search"), "alpha");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "alpha", scheduleId: "sch-a" }),
      ),
    );

    await user.click(screen.getByTestId("tasks-next"));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2, q: "alpha", scheduleId: "sch-a" }),
      ),
    );

    await user.click(screen.getByTestId("tasks-page-size"));
    await user.click(await screen.findByRole("option", { name: "50 / Per page" }));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({
          page: 1,
          pageSize: 50,
          q: "alpha",
          scheduleId: "sch-a",
        }),
      ),
    );

    await user.click(screen.getByText("Refresh"));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "alpha", scheduleId: "sch-a" }),
      ),
    );
  });
});
