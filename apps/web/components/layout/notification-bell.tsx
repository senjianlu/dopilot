"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Bell, CheckCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription, EmptyMedia } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationsRead,
} from "@/lib/api/notifications";
import type { NotificationItem } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

// Notification center bell (log-flood guard / auto-disable): unread badge,
// dropdown of the latest notifications rendered via i18n by type + payload,
// "mark all read", and click-to-navigate (schedule -> schedules page,
// log alerts -> the task detail route).
export const UNREAD_POLL_MS = 30_000;

function formatBadge(count: number): string {
  return count > 99 ? "99+" : String(count);
}

// Where a notification takes the user. Uses the existing STATIC routes only
// (`/tasks/detail?id=` — there is no dynamic `/tasks/<id>` page).
export function notificationHref(item: NotificationItem): string | null {
  const p = item.payload ?? {};
  switch (item.type) {
    case "schedule_auto_disabled": {
      const id = typeof p.schedule_id === "string" ? p.schedule_id : "";
      return id ? `/schedules?highlight=${encodeURIComponent(id)}` : "/schedules";
    }
    case "attempt_no_progress":
    case "log_flood":
    case "log_truncated": {
      const id = typeof p.task_id === "string" ? p.task_id : "";
      return id ? `/tasks/detail?id=${encodeURIComponent(id)}` : "/tasks";
    }
    case "redis_stream_over_budget":
    case "logs_dir_over_budget":
    case "stale_command_streams_deleted":
    case "sent_commands_requeued":
      return "/maintenance";
    default:
      return null;
  }
}

// Semantic tokens only (shadcn convention): error -> destructive, warning ->
// primary, info -> muted.
function severityClass(severity: string): string {
  switch (severity) {
    case "error":
      return "bg-destructive";
    case "warning":
      return "bg-primary";
    default:
      return "bg-muted-foreground";
  }
}

export function NotificationBell() {
  const { t } = useTranslation();
  const router = useRouter();
  const [unread, setUnread] = React.useState(0);
  const [items, setItems] = React.useState<NotificationItem[]>([]);
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);

  const refreshCount = React.useCallback(async () => {
    try {
      setUnread(await getUnreadCount());
    } catch {
      // transient API failure: keep the last known badge
    }
  }, []);

  React.useEffect(() => {
    void refreshCount();
    const timer = setInterval(() => void refreshCount(), UNREAD_POLL_MS);
    return () => clearInterval(timer);
  }, [refreshCount]);

  const loadList = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await listNotifications({ limit: 20 });
      setItems(res.notifications);
      setUnread(res.unread_count);
    } catch {
      // keep whatever was shown
    } finally {
      setLoading(false);
    }
  }, []);

  async function onOpenChange(next: boolean) {
    setOpen(next);
    if (next) await loadList();
  }

  async function onItemClick(item: NotificationItem) {
    if (!item.read) {
      try {
        await markNotificationsRead([item.id]);
        setItems((prev) =>
          prev.map((n) => (n.id === item.id ? { ...n, read: true } : n)),
        );
        setUnread((n) => Math.max(0, n - 1));
      } catch {
        // navigation still proceeds
      }
    }
    const href = notificationHref(item);
    setOpen(false);
    if (href) router.push(href);
  }

  async function onMarkAll() {
    try {
      await markAllNotificationsRead();
      setItems((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnread(0);
    } catch {
      // ignore; next poll refreshes
    }
  }

  function render(item: NotificationItem): { title: string; body: string } {
    const key = `notifications.types.${item.type}`;
    const vars = {
      ...item.payload,
      count: item.count,
      defaultValue: "",
    } as Record<string, unknown>;
    // i18next context suffix: a notification whose payload says the task was
    // stopped for the user reads as a different sentence than one that only
    // reports the condition, and `<key>.body_stopped` keeps both in the locale
    // file instead of assembling them here.
    if (item.payload?.auto_stopped === true) {
      vars.context = "stopped";
    }
    const title = t(`${key}.title`, { ...vars, defaultValue: item.type });
    const body = t(`${key}.body`, { ...vars, defaultValue: "" });
    return { title, body };
  }

  return (
    <DropdownMenu open={open} onOpenChange={(v) => void onOpenChange(v)}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={t("notifications.title")}
          data-testid="notification-bell"
        >
          <Bell />
          {unread > 0 ? (
            <Badge
              variant="destructive"
              data-testid="notification-badge"
              className="absolute -top-1 -right-1 min-w-4 px-1 py-0 text-[10px] leading-4 font-semibold"
            >
              {formatBadge(unread)}
            </Badge>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-96 max-w-[calc(100vw-2rem)]"
        data-testid="notification-menu"
      >
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>{t("notifications.title")}</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={(e) => {
              e.preventDefault();
              void onMarkAll();
            }}
            data-testid="notification-mark-all"
            disabled={unread === 0}
          >
            <CheckCheck data-icon="inline-start" />
            {t("notifications.markAllRead")}
          </Button>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {loading && items.length === 0 ? (
          <Empty className="py-6">
            <EmptyMedia variant="icon">
              <Spinner />
            </EmptyMedia>
            <EmptyDescription>{t("notifications.loading")}</EmptyDescription>
          </Empty>
        ) : items.length === 0 ? (
          <Empty className="py-6" data-testid="notification-empty">
            <EmptyMedia variant="icon">
              <Bell />
            </EmptyMedia>
            <EmptyDescription>{t("notifications.empty")}</EmptyDescription>
          </Empty>
        ) : (
          <DropdownMenuGroup className="max-h-96 overflow-y-auto">
            {items.map((item) => {
              const { title, body } = render(item);
              return (
                <DropdownMenuItem
                  key={item.id}
                  className="flex cursor-pointer flex-col items-start gap-0.5 py-2"
                  onSelect={(e) => {
                    e.preventDefault();
                    void onItemClick(item);
                  }}
                  data-testid={`notification-item-${item.type}`}
                  data-read={item.read ? "true" : "false"}
                >
                  <span className="flex w-full items-center gap-2">
                    <span
                      className={cn(
                        "size-2 shrink-0 rounded-full",
                        severityClass(item.severity),
                      )}
                      aria-hidden
                    />
                    <span
                      className={cn("truncate text-sm", !item.read && "font-semibold")}
                    >
                      {title}
                    </span>
                    {item.count > 1 ? (
                      <span className="ml-auto text-xs text-muted-foreground">
                        ×{item.count}
                      </span>
                    ) : null}
                  </span>
                  {body ? (
                    <span className="line-clamp-2 text-xs text-muted-foreground">
                      {body}
                    </span>
                  ) : null}
                  <span className="text-[10px] text-muted-foreground">
                    {formatDateTime(item.last_seen_at ?? item.created_at)}
                  </span>
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuGroup>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
