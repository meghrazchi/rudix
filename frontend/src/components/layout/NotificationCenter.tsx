"use client";

import Link from "next/link";
import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  markNotificationUnread,
  type NotificationEventType,
  type NotificationResponse,
  type NotificationSeverity,
} from "@/lib/api/notification-center";
import { queryKeys } from "@/lib/api/query";
import { isExternalHref } from "@/lib/public-site/links";

// ---------------------------------------------------------------------------
// Severity styling
// ---------------------------------------------------------------------------

function severityBadgeClass(severity: NotificationSeverity): string {
  switch (severity) {
    case "error":
      return "bg-rose-100 text-rose-700";
    case "warning":
      return "bg-amber-100 text-amber-700";
    default:
      return "bg-[#ede9ff] text-[#5d58a8]";
  }
}

function eventIcon(eventType: NotificationEventType): string {
  switch (eventType) {
    case "upload_indexed":
      return "check_circle";
    case "upload_failed":
      return "error";
    case "evaluation_complete":
      return "fact_check";
    case "evaluation_failed":
      return "cancel";
    case "invite_received":
      return "person_add";
    case "security_warning":
      return "security";
    case "quota_warning":
      return "warning";
    case "connector_sync_issue":
      return "sync_problem";
  }
}

function eventIconColor(eventType: NotificationEventType): string {
  switch (eventType) {
    case "upload_failed":
    case "evaluation_failed":
      return "text-rose-500";
    case "security_warning":
    case "quota_warning":
    case "connector_sync_issue":
      return "text-amber-500";
    default:
      return "text-[#3525cd]";
  }
}

function formatTime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  const diff = Date.now() - parsed;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(parsed).toLocaleDateString();
}

// ---------------------------------------------------------------------------
// Notification item
// ---------------------------------------------------------------------------

function NotificationItem({
  notification,
  onMarkRead,
  onMarkUnread,
  onNavigate,
}: {
  notification: NotificationResponse;
  onMarkRead: (id: string) => void;
  onMarkUnread: (id: string) => void;
  onNavigate: () => void;
}) {
  const isExternal = notification.href ? isExternalHref(notification.href) : false;

  const content = (
    <div className="flex min-w-0 flex-1 items-start gap-3">
      <span
        aria-hidden="true"
        className={`material-symbols-outlined mt-0.5 shrink-0 text-[18px] ${eventIconColor(notification.event_type)}`}
        style={{ fontVariationSettings: "'FILL' 1" }}
      >
        {eventIcon(notification.event_type)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p
            className={`truncate text-sm font-semibold ${notification.is_read ? "text-[#68647b]" : "text-[#2f2a46]"}`}
          >
            {notification.title}
          </p>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${severityBadgeClass(notification.severity)}`}
          >
            {notification.severity}
          </span>
        </div>
        {notification.message ? (
          <p className="mt-0.5 text-xs text-[#5f5a74]">{notification.message}</p>
        ) : null}
        <p className="mt-1 text-[11px] text-[#9c98b0]">
          {formatTime(notification.created_at)}
        </p>
      </div>
    </div>
  );

  return (
    <li
      className={`group relative rounded-lg border p-3 transition-colors ${
        notification.is_read
          ? "border-[#ebe8f4] bg-white"
          : "border-[#d4cfed] bg-[#f8f7ff]"
      }`}
    >
      {notification.href ? (
        <Link
          href={notification.href}
          role="menuitem"
          onClick={onNavigate}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noreferrer noopener" : undefined}
          className="flex items-start hover:opacity-80"
        >
          {content}
        </Link>
      ) : (
        <div className="flex items-start">{content}</div>
      )}

      <div className="mt-2 flex justify-end gap-1">
        {notification.is_read ? (
          <button
            type="button"
            onClick={() => onMarkUnread(notification.notification_id)}
            className="rounded px-1.5 py-0.5 text-[10px] font-medium text-[#7c78a0] hover:bg-[#ede9ff] hover:text-[#3525cd]"
          >
            Mark unread
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onMarkRead(notification.notification_id)}
            className="rounded px-1.5 py-0.5 text-[10px] font-medium text-[#7c78a0] hover:bg-[#ede9ff] hover:text-[#3525cd]"
          >
            Mark read
          </button>
        )}
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Preferences placeholder
// ---------------------------------------------------------------------------

const PREFERENCE_GROUPS = [
  { label: "Documents", keys: ["upload_indexed", "upload_failed"] },
  { label: "Evaluations", keys: ["evaluation_complete", "evaluation_failed"] },
  { label: "Team & Security", keys: ["invite_received", "security_warning", "quota_warning", "connector_sync_issue"] },
] as const;

function NotificationPreferences({
  onClose,
}: {
  onClose: () => void;
}) {
  return (
    <div className="space-y-3 p-1">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-[#2f2a46]">
          Notification preferences
        </p>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-0.5 text-[#7c78a0] hover:bg-[#ede9ff]"
          aria-label="Close preferences"
        >
          <span className="material-symbols-outlined text-[16px]">close</span>
        </button>
      </div>
      <p className="text-xs text-[#7c78a0]">
        Choose which notification categories you receive. Full preference
        management will be available in a future release.
      </p>
      {PREFERENCE_GROUPS.map((group) => (
        <div key={group.label}>
          <p className="mb-1 text-[10px] font-bold tracking-[0.12em] text-[#5d58a8] uppercase">
            {group.label}
          </p>
          <div className="space-y-1">
            {group.keys.map((key) => (
              <label
                key={key}
                className="flex cursor-not-allowed items-center gap-2 rounded px-2 py-1 text-xs text-[#68647b] opacity-60"
              >
                <input
                  type="checkbox"
                  defaultChecked
                  disabled
                  className="accent-[#3525cd]"
                />
                {key.replace(/_/g, " ")}
              </label>
            ))}
          </div>
        </div>
      ))}
      <p className="rounded-md bg-[#faf9ff] px-3 py-2 text-[10px] text-[#7c78a0]">
        Per-category preferences are coming soon.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main NotificationCenter
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

export type NotificationCenterHandle = {
  unreadCount: number;
};

export function NotificationCenter({
  isOpen,
  onNavigate,
  menuRef,
}: {
  isOpen: boolean;
  onNavigate: () => void;
  menuRef?: React.RefObject<HTMLDivElement | null>;
}) {
  const queryClient = useQueryClient();
  const [showPreferences, setShowPreferences] = useState(false);
  const [offset, setOffset] = useState(0);

  const notificationsQuery = useQuery({
    queryKey: queryKeys.notifications.list({ limit: PAGE_SIZE, offset }),
    queryFn: () => listNotifications({ limit: PAGE_SIZE, offset }),
    enabled: isOpen,
    refetchInterval: isOpen ? 30_000 : false,
  });

  const markReadMutation = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.notifications.all,
      });
    },
  });

  const markUnreadMutation = useMutation({
    mutationFn: markNotificationUnread,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.notifications.all,
      });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.notifications.all,
      });
    },
  });

  const data = notificationsQuery.data;
  const hasMore = data ? offset + PAGE_SIZE < data.total : false;
  const hasPrev = offset > 0;

  if (!isOpen) return null;

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Notifications menu"
      className="absolute right-0 z-50 mt-2 w-[380px] rounded-xl border border-[#d7d4e8] bg-white shadow-xl"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#ebe8f4] px-4 py-3">
        <div className="flex items-center gap-2">
          <p className="text-xs font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
            Notifications
          </p>
          {data && data.unread_count > 0 ? (
            <span className="inline-flex min-w-5 justify-center rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
              {data.unread_count}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-1">
          {data && data.unread_count > 0 ? (
            <button
              type="button"
              onClick={() => markAllReadMutation.mutate()}
              disabled={markAllReadMutation.isPending}
              className="rounded px-2 py-1 text-[11px] font-semibold text-[#5d58a8] hover:bg-[#f0ecff] disabled:opacity-50"
            >
              Mark all read
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setShowPreferences((prev) => !prev)}
            aria-label="Notification preferences"
            className="rounded p-1 text-[#7c78a0] hover:bg-[#f0ecff]"
          >
            <span className="material-symbols-outlined text-[16px]">
              settings
            </span>
          </button>
        </div>
      </div>

      {/* Preferences panel */}
      {showPreferences ? (
        <div className="border-b border-[#ebe8f4] px-4 py-3">
          <NotificationPreferences onClose={() => setShowPreferences(false)} />
        </div>
      ) : null}

      {/* Body */}
      <div className="max-h-[420px] overflow-y-auto p-3">
        {notificationsQuery.isLoading ? (
          <p className="py-4 text-center text-sm text-[#68647b]">
            Loading notifications…
          </p>
        ) : notificationsQuery.isError ? (
          <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50 p-3">
            <p className="text-sm text-rose-700">
              {getApiErrorMessage(notificationsQuery.error)}
            </p>
            <button
              type="button"
              data-menu-autofocus="true"
              onClick={() => void notificationsQuery.refetch()}
              className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-100"
            >
              Retry
            </button>
          </div>
        ) : !data || data.items.length === 0 ? (
          <p
            data-menu-autofocus="true"
            className="py-6 text-center text-sm text-[#68647b]"
          >
            You&apos;re all caught up — no notifications yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {data.items.map((n) => (
              <NotificationItem
                key={n.notification_id}
                notification={n}
                onMarkRead={(id) => markReadMutation.mutate(id)}
                onMarkUnread={(id) => markUnreadMutation.mutate(id)}
                onNavigate={onNavigate}
              />
            ))}
          </ul>
        )}
      </div>

      {/* Pagination */}
      {data && data.total > PAGE_SIZE ? (
        <div className="flex items-center justify-between border-t border-[#ebe8f4] px-4 py-2">
          <button
            type="button"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={!hasPrev}
            className="rounded px-2 py-1 text-xs font-semibold text-[#5d58a8] hover:bg-[#f0ecff] disabled:opacity-30"
          >
            ← Newer
          </button>
          <span className="text-[11px] text-[#9c98b0]">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of{" "}
            {data.total}
          </span>
          <button
            type="button"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={!hasMore}
            className="rounded px-2 py-1 text-xs font-semibold text-[#5d58a8] hover:bg-[#f0ecff] disabled:opacity-30"
          >
            Older →
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lightweight hook for the always-on unread count badge (polling)
// ---------------------------------------------------------------------------

export function useNotificationUnreadCount(): number {
  const query = useQuery({
    queryKey: queryKeys.notifications.unreadCount,
    queryFn: getUnreadCount,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
  return query.data?.unread_count ?? 0;
}
