import client from "./client";
import type {
  NotificationsReadResponse,
  NotificationsResponse,
  NotificationUnreadCountResponse,
} from "./types";

// Notification center (log-flood guard / auto-disable). The bell polls the
// unread count and fetches the list when the dropdown opens.
export async function listNotifications(params?: {
  unread_only?: boolean;
  limit?: number;
  before?: string;
}): Promise<NotificationsResponse> {
  const { data } = await client.get<NotificationsResponse>("/notifications", {
    params: {
      unread_only: params?.unread_only ?? false,
      limit: params?.limit ?? 20,
      ...(params?.before ? { before: params.before } : {}),
    },
  });
  return data;
}

export async function getUnreadCount(): Promise<number> {
  const { data } = await client.get<NotificationUnreadCountResponse>(
    "/notifications/unread-count",
  );
  return data.unread_count;
}

export async function markNotificationsRead(
  ids: string[],
): Promise<NotificationsReadResponse> {
  const { data } = await client.post<NotificationsReadResponse>(
    "/notifications/read",
    { ids },
  );
  return data;
}

export async function markAllNotificationsRead(): Promise<NotificationsReadResponse> {
  const { data } = await client.post<NotificationsReadResponse>(
    "/notifications/read-all",
  );
  return data;
}
