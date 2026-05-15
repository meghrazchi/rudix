import type { AppRole } from "@/lib/auth-session";
import { apiRequest } from "@/lib/api/request";

export type TopBarNotificationSeverity = "info" | "warning" | "error";
export type TopBarNotificationKind =
  | "failed_job"
  | "low_confidence"
  | "usage_warning"
  | "backend_unavailable"
  | "generic";

export type TopBarNotification = {
  id: string;
  title: string;
  message: string | null;
  created_at: string | null;
  severity: TopBarNotificationSeverity;
  kind: TopBarNotificationKind;
  href: string | null;
  allowed_roles?: AppRole[];
};

export type TopBarNotificationsResponse = {
  items: TopBarNotification[];
};

export async function getTopBarNotifications(endpoint: string): Promise<TopBarNotificationsResponse> {
  return apiRequest<TopBarNotificationsResponse>(endpoint);
}
