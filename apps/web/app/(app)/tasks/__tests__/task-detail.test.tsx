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
});

afterEach(() => vi.clearAllMocks());

describe("TaskDetailPage", () => {
  it("renders the task status and its child executions", async () => {
    renderWithProviders(<TaskDetailPage />);
    await waitFor(() => expect(getTask).toHaveBeenCalledWith("task-1"));
    expect(await screen.findByTestId("task-status")).toHaveTextContent("running");
    expect(screen.getByTestId("execution-agent-agent-1")).toBeInTheDocument();
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
