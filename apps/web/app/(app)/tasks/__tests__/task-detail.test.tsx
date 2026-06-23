import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type { TaskView } from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("id=task-1"),
}));

const getTask = vi.fn();
const cancelTask = vi.fn();
vi.mock("@/lib/api/tasks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/tasks")>();
  return {
    ...actual,
    getTask: (id: string) => getTask(id),
    cancelTask: (id: string) => cancelTask(id),
  };
});
const markTaskLost = vi.fn();
vi.mock("@/lib/api/maintenance", () => ({
  markTaskLost: (id: string) => markTaskLost(id),
}));

const logViewerMock = vi.hoisted(() =>
  vi.fn(({ executionId }: { taskId: string; executionId?: string }) => (
    <div data-testid="log-viewer" data-execution-id={executionId ?? ""} />
  )),
);
vi.mock("@/components/features/log-viewer", () => ({
  LogViewer: logViewerMock,
}));

import TaskDetailPage from "@/app/(app)/tasks/detail/page";

function makeTask(overrides: Partial<TaskView> = {}): TaskView {
  return {
    id: "task-1",
    artifact_type: "scrapy",
    target: "demo",
    status: "running",
    node_strategy: "all",
    params: { command: "scrapy crawl phase1" },
    build_artifact: { name: "demo" },
    created_at: "2026-06-19T00:00:00Z",
    started_at: null,
    finished_at: null,
    executions: [
      {
        id: "ex-1",
        task_id: "task-1",
        agent_id: "agent-1",
        node_id: "node-1",
        endpoint: "http://a1:6800",
        remote_job_id: "job-1",
        status: "running",
        started_at: null,
        finished_at: null,
        exit_code: null,
        error_code: null,
        error_detail: null,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  getTask.mockReset().mockResolvedValue(makeTask());
  cancelTask.mockReset().mockResolvedValue(makeTask({ status: "canceled" }));
  markTaskLost.mockReset().mockResolvedValue({
    task_id: "task-1",
    task_status: "lost",
    executions_marked: 1,
    already_terminal: [],
  });
  logViewerMock.mockClear();
});

afterEach(() => vi.clearAllMocks());

describe("TaskDetailPage", () => {
  it("renders the task status and its child executions", async () => {
    renderWithProviders(<TaskDetailPage />);
    await waitFor(() => expect(getTask).toHaveBeenCalledWith("task-1"));
    expect(await screen.findByTestId("task-status")).toHaveTextContent("running");
    expect(screen.getByTestId("execution-agent-agent-1")).toBeInTheDocument();
    expect(screen.getByTestId("log-viewer")).toHaveAttribute(
      "data-execution-id",
      "ex-1",
    );
    expect(screen.queryByTestId("execution-log-tab-ex-1")).not.toBeInTheDocument();
  });

  it("switches the log viewer between child executions", async () => {
    const user = userEvent.setup();
    getTask.mockResolvedValue(
      makeTask({
        executions: [
          {
            id: "ex-1",
            task_id: "task-1",
            agent_id: "agent-1",
            node_id: "node-1",
            endpoint: "http://a1:6800",
            remote_job_id: "job-1",
            status: "running",
            started_at: null,
            finished_at: null,
            exit_code: null,
            error_code: null,
            error_detail: null,
          },
          {
            id: "ex-2",
            task_id: "task-1",
            agent_id: "agent-2",
            node_id: "node-2",
            endpoint: "http://a2:6800",
            remote_job_id: "job-2",
            status: "running",
            started_at: null,
            finished_at: null,
            exit_code: null,
            error_code: null,
            error_detail: null,
          },
        ],
      }),
    );

    renderWithProviders(<TaskDetailPage />);
    await waitFor(() =>
      expect(screen.getByTestId("log-viewer")).toHaveAttribute(
        "data-execution-id",
        "ex-1",
      ),
    );

    await user.click(screen.getByTestId("execution-log-tab-ex-2"));

    await waitFor(() =>
      expect(screen.getByTestId("log-viewer")).toHaveAttribute(
        "data-execution-id",
        "ex-2",
      ),
    );
  });

  it("orders executions/log tabs by agent_id, then id, with null agent last", async () => {
    function ex(id: string, agentId: string | null) {
      return {
        id,
        task_id: "task-1",
        agent_id: agentId,
        node_id: null,
        endpoint: null,
        remote_job_id: null,
        status: "running",
        started_at: null,
        finished_at: null,
        exit_code: null,
        error_code: null,
        error_detail: null,
      };
    }
    // Deliberately unsorted: agent-c, null, agent-a, plus a duplicate agent-a
    // (id tie-breaker). Expected order: agent-a/ex-a1, agent-a/ex-a2, agent-c,
    // then the null-agent execution last.
    getTask.mockResolvedValue(
      makeTask({
        executions: [
          ex("ex-c", "agent-c"),
          ex("ex-null", null),
          ex("ex-a2", "agent-a"),
          ex("ex-a1", "agent-a"),
        ],
      }),
    );

    renderWithProviders(<TaskDetailPage />);
    // Default selection is the first sorted execution (agent-a, id ex-a1).
    await waitFor(() =>
      expect(screen.getByTestId("log-viewer")).toHaveAttribute(
        "data-execution-id",
        "ex-a1",
      ),
    );

    const tabs = screen
      .getAllByTestId(/^execution-log-tab-/)
      .map((el) => el.getAttribute("data-testid"));
    expect(tabs).toEqual([
      "execution-log-tab-ex-a1",
      "execution-log-tab-ex-a2",
      "execution-log-tab-ex-c",
      "execution-log-tab-ex-null",
    ]);
  });

  it("cancels an active task after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TaskDetailPage />);
    const cancelBtn = await screen.findByTestId("task-cancel");
    await user.click(cancelBtn);
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(cancelTask).toHaveBeenCalledWith("task-1"));
  });

  it("marks an active task lost after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TaskDetailPage />);
    const markBtn = await screen.findByTestId("task-mark-lost");
    await user.click(markBtn);
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(markTaskLost).toHaveBeenCalledWith("task-1"));
  });

  it("hides cancel / mark-lost on a terminal task", async () => {
    getTask.mockResolvedValue(makeTask({ status: "complete" }));
    renderWithProviders(<TaskDetailPage />);
    await waitFor(() => expect(getTask).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("task-status")).toHaveTextContent("complete"),
    );
    expect(screen.queryByTestId("task-cancel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("task-mark-lost")).not.toBeInTheDocument();
  });
});
