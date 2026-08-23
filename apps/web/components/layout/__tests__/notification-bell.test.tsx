import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import i18n from "@/lib/i18n/config";
import type { NotificationItem } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/dashboard",
}));

const getUnreadCount = vi.fn();
const listNotifications = vi.fn();
const markNotificationsRead = vi.fn();
const markAllNotificationsRead = vi.fn();
vi.mock("@/lib/api/notifications", () => ({
  getUnreadCount: () => getUnreadCount(),
  listNotifications: (p: unknown) => listNotifications(p),
  markNotificationsRead: (ids: string[]) => markNotificationsRead(ids),
  markAllNotificationsRead: () => markAllNotificationsRead(),
}));

import { TopControls } from "@/components/layout/top-controls";
import { notificationHref } from "@/components/layout/notification-bell";

const scheduleNote: NotificationItem = {
  id: "n-1",
  type: "schedule_auto_disabled",
  severity: "error",
  payload: {
    schedule_id: "sch-9",
    schedule_name: "steammarket-c5",
    consecutive_errors: 5,
    threshold: 5,
  },
  count: 1,
  read: false,
  read_at: null,
  created_at: "2026-08-22T12:00:00+00:00",
  last_seen_at: "2026-08-22T12:00:00+00:00",
};
const floodNote: NotificationItem = {
  id: "n-2",
  type: "log_flood",
  severity: "warning",
  payload: {
    task_id: "task-42",
    execution_id: "exec-42",
    agent_id: "agent-01",
    log_bytes: 40000000,
    cap: 33554432,
  },
  count: 3,
  read: false,
  read_at: null,
  created_at: "2026-08-22T11:59:00+00:00",
  last_seen_at: "2026-08-22T12:01:00+00:00",
};

beforeEach(() => {
  push.mockReset();
  getUnreadCount.mockReset().mockResolvedValue(3);
  listNotifications.mockReset().mockResolvedValue({
    notifications: [scheduleNote, floodNote],
    unread_count: 3,
  });
  markNotificationsRead.mockReset().mockResolvedValue({ marked: 1 });
  markAllNotificationsRead.mockReset().mockResolvedValue({ marked: 3 });
});

afterEach(() => {
  vi.clearAllMocks();
  void i18n.changeLanguage("zh");
});

describe("NotificationBell (TC-28)", () => {
  it("shows the unread badge, lists items via i18n, navigates and marks read", async () => {
    await i18n.changeLanguage("zh");
    const user = userEvent.setup();
    renderWithProviders(<TopControls />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-badge")).toHaveTextContent("3"),
    );
    // the counter is the shadcn Badge (destructive variant), not a hand-rolled span
    const badge = screen.getByTestId("notification-badge");
    expect(badge).toHaveAttribute("data-slot", "badge");
    expect(badge).toHaveAttribute("data-variant", "destructive");

    await user.click(screen.getByTestId("notification-bell"));
    const menu = await screen.findByTestId("notification-menu");
    expect(listNotifications).toHaveBeenCalled();
    const scheduleItem = within(menu).getByTestId(
      "notification-item-schedule_auto_disabled",
    );
    // zh copy, rendered from type + payload (never a raw key / raw type)
    expect(scheduleItem).toHaveTextContent("steammarket-c5");
    expect(scheduleItem).toHaveTextContent("已被自动禁用");
    expect(scheduleItem.textContent).not.toContain("notifications.types");
    const floodItem = within(menu).getByTestId("notification-item-log_flood");
    expect(floodItem).toHaveTextContent("日志洪泛");
    expect(floodItem).toHaveTextContent("×3");

    await user.click(scheduleItem);
    await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledWith(["n-1"]));
    expect(push).toHaveBeenCalledWith("/schedules?highlight=sch-9");

    await user.click(screen.getByTestId("notification-bell"));
    const floodAgain = await screen.findByTestId("notification-item-log_flood");
    await user.click(floodAgain);
    await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledWith(["n-2"]));
    expect(push).toHaveBeenCalledWith("/tasks/detail?id=task-42");

    await user.click(screen.getByTestId("notification-bell"));
    await user.click(await screen.findByTestId("notification-mark-all"));
    await waitFor(() => expect(markAllNotificationsRead).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId("notification-badge")).not.toBeInTheDocument(),
    );
  });

  it("renders English copy for every type without missing keys", async () => {
    await i18n.changeLanguage("en");
    const all: NotificationItem[] = [
      scheduleNote,
      floodNote,
      { ...floodNote, id: "n-3", type: "log_truncated",
        payload: { task_id: "t", execution_id: "e", reason: "size-cap" } },
      { ...floodNote, id: "n-4", type: "redis_stream_over_budget",
        payload: { initial_bytes: 1, budget: 2, trimmed: 3, cleared: false } },
      { ...floodNote, id: "n-5", type: "logs_dir_over_budget",
        payload: { bytes: 1, budget: 2 } },
      { ...floodNote, id: "n-6", type: "stale_command_streams_deleted",
        payload: { agent_ids: ["ghost"], count: 1 } },
      { ...floodNote, id: "n-7", type: "sent_commands_requeued",
        payload: { count: 2 } },
    ];
    listNotifications.mockResolvedValue({ notifications: all, unread_count: 7 });
    const user = userEvent.setup();
    renderWithProviders(<TopControls />);
    await user.click(await screen.findByTestId("notification-bell"));
    const menu = await screen.findByTestId("notification-menu");
    expect(within(menu).getByTestId("notification-item-schedule_auto_disabled"))
      .toHaveTextContent("was disabled automatically");
    for (const n of all) {
      const item = within(menu).getByTestId(`notification-item-${n.type}`);
      expect(item.textContent).not.toContain("notifications.types");
      expect(item.textContent ?? "").not.toEqual("");
    }
  });

  it("caps the badge at 99+", async () => {
    getUnreadCount.mockResolvedValue(120);
    renderWithProviders(<TopControls />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-badge")).toHaveTextContent("99+"),
    );
  });

  it("maps notification types onto existing static routes", () => {
    expect(notificationHref(scheduleNote)).toBe("/schedules?highlight=sch-9");
    expect(notificationHref(floodNote)).toBe("/tasks/detail?id=task-42");
    expect(notificationHref({ ...floodNote, type: "logs_dir_over_budget" })).toBe(
      "/maintenance",
    );
    expect(notificationHref({ ...floodNote, type: "unknown_type" })).toBeNull();
  });
});
