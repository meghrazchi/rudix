import type { components } from "@/lib/api/generated/schema";
import { apiRequest } from "@/lib/api/request";

export type NotificationResponse =
  components["schemas"]["NotificationResponse"];
export type NotificationListResponse =
  components["schemas"]["NotificationListResponse"];
export type MarkReadResponse = components["schemas"]["MarkReadResponse"];
export type MarkAllReadResponse = components["schemas"]["MarkAllReadResponse"];
export type UnreadCountResponse = components["schemas"]["UnreadCountResponse"];

export type NotificationEventType = NotificationResponse["event_type"];
export type NotificationSeverity = NotificationResponse["severity"];

export async function listNotifications(params?: {
  limit?: number;
  offset?: number;
}): Promise<NotificationListResponse> {
  const query: Record<string, string> = {};
  if (params?.limit !== undefined) query.limit = String(params.limit);
  if (params?.offset !== undefined) query.offset = String(params.offset);
  return apiRequest<NotificationListResponse>("/notifications", { query });
}

export async function getUnreadCount(): Promise<UnreadCountResponse> {
  return apiRequest<UnreadCountResponse>("/notifications/unread-count");
}

export async function markNotificationRead(
  notificationId: string,
): Promise<MarkReadResponse> {
  return apiRequest<MarkReadResponse>(`/notifications/${notificationId}/read`, {
    method: "PATCH",
  });
}

export async function markNotificationUnread(
  notificationId: string,
): Promise<MarkReadResponse> {
  return apiRequest<MarkReadResponse>(
    `/notifications/${notificationId}/unread`,
    { method: "PATCH" },
  );
}

export async function markAllNotificationsRead(): Promise<MarkAllReadResponse> {
  return apiRequest<MarkAllReadResponse>("/notifications/mark-all-read", {
    method: "POST",
  });
}
