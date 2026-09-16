import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
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
const disableAllSchedules = vi.fn();
vi.mock("@/lib/api/schedules", () => ({
  listSchedules: () => listSchedules(),
  deleteSchedule: (id: string) => deleteSchedule(id),
  triggerSchedule: (id: string) => triggerSchedule(id),
  previewNextRun: (p: unknown) => previewNextRun(p),
  createSchedule: (p: unknown) => createSchedule(p),
  updateSchedule: (id: string, p: unknown) => updateSchedule(id, p),
  disableAllSchedules: () => disableAllSchedules(),
}));
const listTemplates = vi.fn();
vi.mock("@/lib/api/templates", () => ({ listTemplates: () => listTemplates() }));
const listNodes = vi.fn();
vi.mock("@/lib/api/nodes", () => ({ listNodes: () => listNodes() }));
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: (m: string) => toastError(m), success: vi.fn() },
}));

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
  max_concurrency: 1,
  execution_template_id: "tpl-1",
  trigger_type: "interval",
  interval_seconds: 60,
  cron: null,
  overrides: {},
  next_run_at: null,
  consecutive_error_count: 0,
  auto_disabled_at: null,
  auto_disabled_reason: null,
  outcome_generation: 0,
  created_at: null,
  updated_at: null,
};

// listSchedules now returns the full response; enabled_total defaults to the
// enabled rows in the page unless a test overrides it (truncation scenarios).
function schedulesResponse(rows: Schedule[], enabledTotal?: number) {
  return {
    schedules: rows,
    enabled_total: enabledTotal ?? rows.filter((r) => r.enabled).length,
  };
}

beforeEach(() => {
  push.mockReset();
  listSchedules.mockReset().mockResolvedValue(schedulesResponse([schedule]));
  disableAllSchedules.mockReset().mockResolvedValue({ disabled: 1 });
  deleteSchedule.mockReset().mockResolvedValue(undefined);
  triggerSchedule.mockReset().mockResolvedValue({ task_id: "task-7", status: "queued" });
  previewNextRun.mockReset().mockResolvedValue({ next_run_at: null });
  createSchedule.mockReset().mockResolvedValue(schedule);
  updateSchedule.mockReset().mockResolvedValue(schedule);
  listTemplates.mockReset().mockResolvedValue([template]);
  listNodes.mockReset().mockResolvedValue([]);
  toastError.mockReset();
});

afterEach(() => vi.clearAllMocks());

// The per-row actions (tasks / trigger / edit / delete) now live behind a "⋯"
// menu, and Radix mounts menu content only while the menu is open — so every
// action assertion has to open that row's menu first.
async function openRowActions(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  await user.click(await screen.findByTestId(`schedule-actions-${name}`));
}

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
    await openRowActions(user, "demo-schedule");
    await user.click(screen.getByTestId("schedule-trigger-demo-schedule"));
    await waitFor(() => expect(triggerSchedule).toHaveBeenCalledWith("sch-1"));
    expect(push).toHaveBeenCalledWith("/tasks/detail?id=task-7");
  });

  it("edits a schedule: pre-fills the dialog and calls updateSchedule", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await openRowActions(user, "demo-schedule");
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
        max_concurrency: 1,
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
    listSchedules.mockResolvedValue(
      schedulesResponse([{ ...schedule, enabled: true }]),
    );
    renderWithProviders(<SchedulesPage />);
    await openRowActions(user, "demo-schedule");
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
    listSchedules.mockResolvedValue(
      schedulesResponse([
        schedule,
        { ...schedule, id: "sch-2", name: "other-schedule" },
      ]),
    );
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
    await openRowActions(user, "demo-schedule");
    await user.click(screen.getByTestId("schedule-delete-demo-schedule"));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(deleteSchedule).toHaveBeenCalledWith("sch-1"));
  });

  it("disables all schedules after confirmation and reloads", async () => {
    // TC-03: click -> confirm -> exactly one bulk call -> list reload.
    const user = userEvent.setup();
    listSchedules.mockResolvedValue(
      schedulesResponse([{ ...schedule, enabled: true }]),
    );
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-disable-all")).toBeEnabled(),
    );
    listSchedules.mockClear();
    await user.click(screen.getByTestId("schedule-disable-all"));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(disableAllSchedules).toHaveBeenCalledTimes(1));
    // Reload-on-success: the table re-fetches after the bulk call resolves.
    await waitFor(() => expect(listSchedules).toHaveBeenCalled());
  });

  it("does not disable anything when the confirm dialog is cancelled", async () => {
    // TC-04: the cancel path never reaches the API.
    const user = userEvent.setup();
    listSchedules.mockResolvedValue(
      schedulesResponse([{ ...schedule, enabled: true }]),
    );
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-disable-all")).toBeEnabled(),
    );
    await user.click(screen.getByTestId("schedule-disable-all"));
    await user.click(screen.getByTestId("confirm-cancel"));
    expect(disableAllSchedules).not.toHaveBeenCalled();
  });

  it("disables the disable-all button when nothing is enabled globally", async () => {
    // TC-05 (boundary): enabled_total 0 -> button disabled, no dialog on click.
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-name-demo-schedule"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("schedule-disable-all")).toBeDisabled();
    expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
  });

  it("blocks a second click while the bulk disable is in flight", async () => {
    // TC-08: pending request keeps the button disabled; no double submit.
    const user = userEvent.setup();
    listSchedules.mockResolvedValue(
      schedulesResponse([{ ...schedule, enabled: true }]),
    );
    let resolveBulk: (v: { disabled: number }) => void = () => {};
    disableAllSchedules.mockImplementation(
      () =>
        new Promise<{ disabled: number }>((resolve) => {
          resolveBulk = resolve;
        }),
    );
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-disable-all")).toBeEnabled(),
    );
    listSchedules.mockClear();
    await user.click(screen.getByTestId("schedule-disable-all"));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(disableAllSchedules).toHaveBeenCalledTimes(1));

    // In flight: the button is disabled and a second click cannot re-submit.
    const button = screen.getByTestId("schedule-disable-all");
    expect(button).toBeDisabled();
    await user.click(button);
    expect(disableAllSchedules).toHaveBeenCalledTimes(1);

    resolveBulk({ disabled: 1 });
    await waitFor(() => expect(listSchedules).toHaveBeenCalled());
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("keeps disable-all clickable when only unloaded rows are enabled", async () => {
    // TC-10 (truncation): the loaded page is all-disabled but enabled_total
    // says an older, unloaded row is still enabled -> button stays usable.
    const user = userEvent.setup();
    listSchedules.mockResolvedValue(schedulesResponse([schedule], 1));
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-disable-all")).toBeEnabled(),
    );
    await user.click(screen.getByTestId("schedule-disable-all"));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(disableAllSchedules).toHaveBeenCalledTimes(1));
  });

  it("submits max_concurrency on create", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-create")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("schedule-create"));
    const input = await screen.findByTestId("schedule-max-concurrency-input");
    await user.clear(input);
    await user.type(input, "2");
    await user.type(screen.getByTestId("schedule-name-input"), "new-schedule");
    await user.click(screen.getByTestId("schedule-submit"));
    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({ max_concurrency: 2 }),
      ),
    );
  });

  it("prefills and updates max_concurrency on edit", async () => {
    const user = userEvent.setup();
    listSchedules.mockResolvedValue(
      schedulesResponse([{ ...schedule, max_concurrency: 4 }]),
    );
    renderWithProviders(<SchedulesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-concurrency-demo-schedule"),
      ).toHaveTextContent("4"),
    );
    await openRowActions(user, "demo-schedule");
    await user.click(screen.getByTestId("schedule-edit-demo-schedule"));
    const input = await screen.findByTestId("schedule-max-concurrency-input");
    // Pre-filled with the row's own value, not the create-dialog default of 1.
    expect(input).toHaveValue(4);
    await user.clear(input);
    await user.type(input, "3");
    await user.click(screen.getByTestId("schedule-submit"));
    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith(
        "sch-1",
        expect.objectContaining({ max_concurrency: 3 }),
      ),
    );
  });

  it("supports zero as unlimited", async () => {
    const user = userEvent.setup();
    listSchedules.mockResolvedValue(
      schedulesResponse([{ ...schedule, max_concurrency: 0 }]),
    );
    renderWithProviders(<SchedulesPage />);
    // The list must not print a bare 0 for the escape hatch.
    await waitFor(() =>
      expect(
        screen.getByTestId("schedule-concurrency-demo-schedule"),
      ).toHaveTextContent("Unlimited"),
    );

    // Editing that row pre-fills 0 rather than coercing it to 1.
    await openRowActions(user, "demo-schedule");
    await user.click(screen.getByTestId("schedule-edit-demo-schedule"));
    const editInput = await screen.findByTestId(
      "schedule-max-concurrency-input",
    );
    expect(editInput).toHaveValue(0);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    // And 0 survives a create submit (a `Number(v) || 1` would send 1).
    await user.click(screen.getByTestId("schedule-create"));
    const input = await screen.findByTestId("schedule-max-concurrency-input");
    await user.clear(input);
    await user.type(input, "0");
    await user.type(screen.getByTestId("schedule-name-input"), "unlimited-one");
    await user.click(screen.getByTestId("schedule-submit"));
    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({ max_concurrency: 0 }),
      ),
    );
  });

  it("shows a toast when the concurrency limit is hit", async () => {
    const user = userEvent.setup();
    triggerSchedule.mockRejectedValue({
      response: {
        data: {
          code: "schedule.concurrency_limit",
          message_key: "errors.scheduleConcurrencyLimit",
          detail: { active: 1, limit: 1 },
        },
      },
    });
    renderWithProviders(<SchedulesPage />);
    await openRowActions(user, "demo-schedule");
    await user.click(screen.getByTestId("schedule-trigger-demo-schedule"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toContain("1");
    // Nothing was created, so the page must stay put.
    expect(push).not.toHaveBeenCalled();
  });
});

describe("SchedulesPage auto-disable badge (TC-29)", () => {
  it("shows the auto-disabled badge with the consecutive-error tooltip", async () => {
    const disabled: Schedule = {
      ...schedule,
      id: "sch-2",
      name: "flooding-schedule",
      enabled: false,
      consecutive_error_count: 5,
      auto_disabled_at: "2026-08-22T12:10:00+00:00",
      auto_disabled_reason: { consecutive_errors: 5, threshold: 5, task_ids: [] },
      outcome_generation: 0,
    };
    listSchedules.mockResolvedValue(schedulesResponse([schedule, disabled]));
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    const badge = await screen.findByTestId("schedule-auto-disabled-flooding-schedule");
    expect(badge).toHaveTextContent("Auto-disabled");  // test locale is en
    expect(
      screen.queryByTestId("schedule-auto-disabled-demo-schedule"),
    ).not.toBeInTheDocument();
    await user.hover(badge);
    await waitFor(() =>
      expect(
        screen.getAllByText(/after 5 consecutive erroneous runs/).length,
      ).toBeGreaterThan(0),
    );
    await user.unhover(badge);
    // keyboard: the trigger is a real button, focusable via Tab, and focus
    // alone surfaces the reason (no pointer needed)
    expect(badge.tagName).toBe("BUTTON");
    badge.blur();
    await user.keyboard("{Escape}");
    let guard = 0;
    while (document.activeElement !== badge && guard++ < 50) {
      await user.tab();
    }
    expect(badge).toHaveFocus();
    await waitFor(() =>
      expect(
        screen.getAllByText(/after 5 consecutive erroneous runs/).length,
      ).toBeGreaterThan(0),
    );
  });
});

describe("SchedulesPage task drill-down", () => {
  it("links each row to the tasks page filtered by that schedule", async () => {
    // TC-15
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await openRowActions(user, "demo-schedule");
    const link = screen.getByTestId("schedule-tasks-demo-schedule");
    expect(link).toHaveAttribute(
      "href",
      "/tasks?schedule_id=sch-1&schedule_name=demo-schedule",
    );
  });

  it("url-encodes a schedule name that needs escaping", async () => {
    // TC-15 (encoding branch): a name with spaces/& must not break the query.
    listSchedules.mockResolvedValue(
      schedulesResponse([
        { ...schedule, id: "sch 2&x", name: "nightly run & more" },
      ]),
    );
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await openRowActions(user, "nightly run & more");
    const link = screen.getByTestId("schedule-tasks-nightly run & more");
    expect(link).toHaveAttribute(
      "href",
      "/tasks?schedule_id=sch%202%26x&schedule_name=nightly%20run%20%26%20more",
    );
  });
});

// Long schedule/template names are what pushed this table past the card and,
// before min-w-0 on SidebarInset, the whole page past the viewport. These cover
// the truncation contract and the actions menu that replaced the inline buttons.
describe("SchedulesPage long names and the row actions menu", () => {
  const LONG_NAME =
    "steammarket-spider | JUSTONEAPI STEAM_GIFT_CARD_USD_100_TAOBAO_CNY";
  const LONG_TEMPLATE = `${LONG_NAME} | template`;

  function longRow(extra: Partial<Schedule> = {}): Schedule {
    return { ...schedule, name: LONG_NAME, ...extra };
  }

  beforeEach(() => {
    listTemplates.mockResolvedValue([{ ...template, name: LONG_TEMPLATE }]);
    listSchedules.mockResolvedValue(schedulesResponse([longRow()]));
  });

  it("truncates the long schedule and template names", async () => {
    // TC-02
    renderWithProviders(<SchedulesPage />);
    const name = await screen.findByTestId(`schedule-name-text-${LONG_NAME}`);
    const tpl = screen.getByTestId(`schedule-template-text-${LONG_NAME}`);
    for (const el of [name, tpl]) {
      expect(el).toHaveClass("truncate");
      expect(el).toHaveClass("max-w-[15rem]");
    }
    // the DOM keeps the whole string; only the paint is clipped
    expect(name).toHaveTextContent(LONG_NAME);
    expect(tpl).toHaveTextContent(LONG_TEMPLATE);
  });

  it("surfaces the full name by hover and by keyboard focus", async () => {
    // TC-02b: the truncating span IS the tooltip trigger, so the full text is
    // reachable both ways — `title` alone would leave keyboard users out.
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    const name = await screen.findByTestId(`schedule-name-text-${LONG_NAME}`);
    const tpl = screen.getByTestId(`schedule-template-text-${LONG_NAME}`);

    for (const [el, full] of [
      [name, LONG_NAME],
      [tpl, LONG_TEMPLATE],
    ] as const) {
      expect(el).toHaveAttribute("tabindex", "0");
      // baseline: the text exists once (the cell itself), no tooltip yet
      expect(screen.getAllByText(full)).toHaveLength(1);

      await user.hover(el);
      await waitFor(() =>
        expect(screen.getAllByText(full).length).toBeGreaterThan(1),
      );
      // Radix keeps a hoverable tooltip open on pointerleave alone (there is no
      // real pointer geometry in jsdom); Escape is the deterministic dismiss,
      // same as the auto-disabled badge test above.
      await user.unhover(el);
      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.getAllByText(full)).toHaveLength(1));

      // focus()/blur() drive Radix state from outside React's event system,
      // so wrap them in act(...) to keep the update inside a test-owned batch.
      await act(async () => {
        el.focus();
      });
      expect(el).toHaveFocus();
      await waitFor(() =>
        expect(screen.getAllByText(full).length).toBeGreaterThan(1),
      );
      await act(async () => {
        el.blur();
      });
      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.getAllByText(full)).toHaveLength(1));
    }
  });

  it("keeps the four row actions behind the menu", async () => {
    // TC-03
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await screen.findByTestId(`schedule-actions-${LONG_NAME}`);
    const actions = ["tasks", "trigger", "edit", "delete"];

    for (const act of actions) {
      expect(
        screen.queryByTestId(`schedule-${act}-${LONG_NAME}`),
      ).not.toBeInTheDocument();
    }

    await openRowActions(user, LONG_NAME);

    for (const act of actions) {
      expect(screen.getByTestId(`schedule-${act}-${LONG_NAME}`)).toBeVisible();
    }
  });

  it("does not delete from the menu when the confirm is cancelled", async () => {
    // TC-05: destructive path, both branches.
    const user = userEvent.setup();
    renderWithProviders(<SchedulesPage />);
    await openRowActions(user, LONG_NAME);
    await user.click(screen.getByTestId(`schedule-delete-${LONG_NAME}`));
    await user.click(screen.getByTestId("confirm-cancel"));
    expect(deleteSchedule).not.toHaveBeenCalled();

    await openRowActions(user, LONG_NAME);
    await user.click(screen.getByTestId(`schedule-delete-${LONG_NAME}`));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(deleteSchedule).toHaveBeenCalledWith("sch-1"));
  });

  it("keeps the auto-disabled badge and archived mark outside the truncation", async () => {
    // TC-06: structural guard. jsdom computes no layout, so this asserts the
    // badges are NOT descendants of the clipping span — real clipping is
    // verified in the browser run (TC-07).
    listSchedules.mockResolvedValue(
      schedulesResponse([
        longRow({
          auto_disabled_at: "2026-09-15T03:30:00+00:00",
          consecutive_error_count: 5,
          auto_disabled_reason: {
            consecutive_errors: 5,
            threshold: 5,
            task_ids: [],
          },
        }),
      ]),
    );
    listTemplates.mockResolvedValue([
      { ...template, name: LONG_TEMPLATE, build_artifact_archived: true },
    ]);
    renderWithProviders(<SchedulesPage />);

    const badge = await screen.findByTestId(
      `schedule-auto-disabled-${LONG_NAME}`,
    );
    const archived = screen.getByTestId("archived-indicator");
    const nameSpan = screen.getByTestId(`schedule-name-text-${LONG_NAME}`);
    const tplSpan = screen.getByTestId(`schedule-template-text-${LONG_NAME}`);

    expect(nameSpan.contains(badge)).toBe(false);
    expect(tplSpan.contains(archived)).toBe(false);
    expect(badge).toBeVisible();
    expect(archived).toBeVisible();
  });
});
