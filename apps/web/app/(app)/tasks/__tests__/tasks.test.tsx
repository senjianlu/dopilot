import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type {
  BuildArtifactOption,
  TaskSummary,
  TasksResponse,
} from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/tasks",
}));

const listTasks = vi.fn();
vi.mock("@/lib/api/tasks", () => ({
  listTasks: (params: unknown) => listTasks(params),
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
  listTasks.mockReset().mockResolvedValue(makeResponse());
});

afterEach(() => vi.clearAllMocks());

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
