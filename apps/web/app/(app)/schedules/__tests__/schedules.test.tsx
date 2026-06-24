import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type { ExecutionTemplate, Schedule } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/schedules",
}));

const listSchedules = vi.fn();
const deleteSchedule = vi.fn();
const triggerSchedule = vi.fn();
const previewNextRun = vi.fn();
const createSchedule = vi.fn();
const updateSchedule = vi.fn();
vi.mock("@/lib/api/schedules", () => ({
  listSchedules: () => listSchedules(),
  deleteSchedule: (id: string) => deleteSchedule(id),
  triggerSchedule: (id: string) => triggerSchedule(id),
  previewNextRun: (p: unknown) => previewNextRun(p),
  createSchedule: (p: unknown) => createSchedule(p),
  updateSchedule: (id: string, p: unknown) => updateSchedule(id, p),
}));
const listTemplates = vi.fn();
vi.mock("@/lib/api/templates", () => ({ listTemplates: () => listTemplates() }));
const listNodes = vi.fn();
vi.mock("@/lib/api/nodes", () => ({ listNodes: () => listNodes() }));

import SchedulesPage from "@/app/(app)/schedules/page";

const template: ExecutionTemplate = {
  id: "tpl-1",
  name: "demo-template",
  description: null,
  build_artifact_id: "art-1",
  artifact_type: "scrapy",
  project: "demo",
  version: "v1",
  command: "scrapy crawl phase1",
  node_strategy: "all",
  node_ids: [],
  build_artifact_archived: false,
  build_artifact_archived_at: null,
  created_at: null,
  updated_at: null,
};

const schedule: Schedule = {
  id: "sch-1",
  name: "demo-schedule",
  description: null,
  enabled: false,
  execution_template_id: "tpl-1",
  trigger_type: "interval",
  interval_seconds: 60,
  cron: null,
  overrides: {},
  next_run_at: null,
  created_at: null,
  updated_at: null,
};

beforeEach(() => {
  push.mockReset();
  listSchedules.mockReset().mockResolvedValue([schedule]);
  deleteSchedule.mockReset().mockResolvedValue(undefined);
  triggerSchedule.mockReset().mockResolvedValue({ task_id: "task-7", status: "queued" });
  previewNextRun.mockReset().mockResolvedValue({ next_run_at: null });
  createSchedule.mockReset().mockResolvedValue(schedule);
  updateSchedule.mockReset().mockResolvedValue(schedule);
  listTemplates.mockReset().mockResolvedValue([template]);
  listNodes.mockReset().mockResolvedValue([]);
});

afterEach(() => vi.clearAllMocks());

describe("SchedulesPage", () => {
  it("renders schedules with the resolved template name and trigger time", async () => {
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-name-demo-schedule"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("demo-template")).toBeInTheDocument();
    expect(screen.getByText("every 60 seconds")).toBeInTheDocument();
  });

  it("triggers a schedule and navigates to the created task", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-trigger-demo-schedule"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("schedule-trigger-demo-schedule"));
    await waitFor(() => expect(triggerSchedule).toHaveBeenCalledWith("sch-1"));
    expect(push).toHaveBeenCalledWith("/tasks/detail?id=task-7");
  });

  it("edits a schedule: pre-fills the dialog and calls updateSchedule", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-edit-demo-schedule"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("schedule-edit-demo-schedule"));
    await waitFor(() =>
      expect(screen.getByTestId("schedule-dialog")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("schedule-name-input")).toHaveValue(
      "demo-schedule",
    );
    expect(screen.getByTestId("schedule-interval")).toHaveValue(60);
    await user.click(screen.getByTestId("schedule-submit"));
    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith("sch-1", {
        name: "demo-schedule",
        enabled: false,
        execution_template_id: "tpl-1",
        trigger_type: "interval",
        interval_seconds: 60,
        cron: null,
        overrides: undefined,
      }),
    );
    expect(createSchedule).not.toHaveBeenCalled();
  });

  it("creates a schedule with enabled true when the modal switch is on", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-create")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("schedule-create"));
    await waitFor(() =>
      expect(screen.getByTestId("schedule-dialog")).toBeInTheDocument(),
    );
    await user.type(screen.getByTestId("schedule-name-input"), "nightly");
    // The create dialog defaults to disabled; turning the switch on enables it.
    await user.click(screen.getByTestId("schedule-enabled-input"));
    await user.click(screen.getByTestId("schedule-submit"));
    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({ name: "nightly", enabled: true }),
      ),
    );
    expect(updateSchedule).not.toHaveBeenCalled();
  });

  it("pre-fills the edit dialog switch from an enabled schedule", async () => {
    const user = userEvent.setup();
    listSchedules.mockResolvedValue([{ ...schedule, enabled: true }]);
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-edit-demo-schedule"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("schedule-edit-demo-schedule"));
    await waitFor(() =>
      expect(screen.getByTestId("schedule-enabled-input")).toBeChecked(),
    );
    await user.click(screen.getByTestId("schedule-submit"));
    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith(
        "sch-1",
        expect.objectContaining({ enabled: true }),
      ),
    );
  });

  it("quick-toggles a row through updateSchedule and reloads", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-enabled-demo-schedule"),
      ).toBeInTheDocument(),
    );
    listSchedules.mockClear();
    await user.click(screen.getByTestId("schedule-enabled-demo-schedule"));
    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith("sch-1", { enabled: true }),
    );
    // Reload-on-success: the table re-fetches after the toggle resolves.
    await waitFor(() => expect(listSchedules).toHaveBeenCalled());
  });

  it("shows the archived indicator when the resolved template is archived", async () => {
    // Archive state is derived from the loaded templates list (no schedule API
    // change): the referenced template carries build_artifact_archived.
    listTemplates.mockResolvedValue([
      { ...template, build_artifact_archived: true },
    ]);
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-name-demo-schedule"),
      ).toBeInTheDocument(),
    );
    const indicator = screen.getByTestId("archived-indicator");
    expect(indicator).toBeInTheDocument();
    expect(indicator).toHaveAccessibleName("This build is archived");
  });

  it("shows no archived indicator when the resolved template is not archived", async () => {
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-name-demo-schedule"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("archived-indicator")).not.toBeInTheDocument();
  });

  it("filters schedules by name prefix (trim, case-insensitive, startsWith)", async () => {
    const user = userEvent.setup();
    listSchedules.mockResolvedValue([
      schedule,
      { ...schedule, id: "sch-2", name: "other-schedule" },
    ]);
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-name-demo-schedule"),
      ).toBeInTheDocument(),
    );
    const search = screen.getByTestId("schedule-search");

    await user.type(search, "  DEMO");
    expect(
      screen.getByTestId("schedule-name-demo-schedule"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("schedule-name-other-schedule"),
    ).not.toBeInTheDocument();

    // A non-prefix substring matches nothing.
    await user.clear(search);
    await user.type(search, "chedule");
    expect(
      screen.queryByTestId("schedule-name-demo-schedule"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("schedule-name-other-schedule"),
    ).not.toBeInTheDocument();

    // Empty query shows all rows again.
    await user.clear(search);
    expect(
      screen.getByTestId("schedule-name-demo-schedule"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("schedule-name-other-schedule"),
    ).toBeInTheDocument();
  });

  it("deletes a schedule only after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-name-demo-schedule"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByText("Delete"));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(deleteSchedule).toHaveBeenCalledWith("sch-1"));
  });
});
