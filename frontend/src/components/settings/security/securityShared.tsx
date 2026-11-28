"use client";

import { ClipboardList } from "lucide-react";
import { z } from "zod";
import { type AuditEvent } from "@/lib/api/security";
import { type AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";

export function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

export function isAdminLike(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function formatAuthProvider(raw: string | undefined): string {
  if (!raw?.trim()) return "app";
  return raw
    .trim()
    .split(/[\s_-]+/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
    .join(" ");
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Unknown";
  try {
    return new Date(value).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export function formatExpiryMs(ms: number | null): string {
  if (!ms) return "Unknown";
  const now = Date.now();
  if (ms < now) return "Expired";
  const diff = ms - now;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes}m remaining`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h remaining`;
  return `${Math.floor(hours / 24)}d remaining`;
}

export function fromList(list: string[]): string {
  return list.join(", ");
}

export function toList(csv: string): string[] {
  return csv
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// ── Shared sub-components ─────────────────────────────────────────────────────

export function SectionHeader({
  icon: Icon,
  title,
  badge,
}: {
  icon: React.ElementType;
  title: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Icon size={20} className="text-[#3525cd]" aria-hidden="true" />
        <h2 className="text-lg font-semibold text-[#1b1b24]">{title}</h2>
      </div>
      {badge}
    </div>
  );
}

export function DeploymentControlledBadge({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600"
      aria-label="Deployment-controlled"
    >
      {label}
    </span>
  );
}

export function UnavailableRow({
  label,
  description,
  notAvailableMsg,
  unavailableLabel,
}: {
  label: string;
  description?: string;
  notAvailableMsg: string;
  unavailableLabel: string;
}) {
  return (
    <div
      className="flex items-start justify-between gap-4 rounded-xl border border-dashed border-[#c7c4d8] px-4 py-3 opacity-70"
      aria-label={`${label} unavailable`}
    >
      <div>
        <p className="text-sm font-semibold text-[#1b1b24]">{label}</p>
        {description && <p className="text-xs text-[#464555]">{description}</p>}
        <p className="mt-1 text-xs text-[#777587]">{notAvailableMsg}</p>
      </div>
      <span className="shrink-0 rounded-xl border border-dashed border-[#c7c4d8] px-3 py-1.5 text-sm text-[#777587]">
        {unavailableLabel}
      </span>
    </div>
  );
}

export type SaveState = { tone: "success" | "error"; message: string } | null;

export function SaveFeedback({ state }: { state: SaveState }) {
  if (!state) return null;
  const cls =
    state.tone === "success"
      ? "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
      : "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
  return <p className={cls}>{state.message}</p>;
}

export function ToggleSwitch({
  id,
  checked,
  onChange,
  disabled,
}: {
  id?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[
        "relative flex h-6 w-12 shrink-0 items-center rounded-full px-1 transition-colors",
        checked ? "bg-[#3525cd]" : "bg-[#c7c4d8]",
        disabled ? "cursor-not-allowed opacity-60" : "",
      ].join(" ")}
    >
      <div
        className={[
          "h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
          checked ? "translate-x-6" : "translate-x-0",
        ].join(" ")}
      />
    </button>
  );
}

export function FieldLabel({
  htmlFor,
  children,
}: {
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
    >
      {children}
    </label>
  );
}

export function BoolBadge({
  value,
  yesLabel,
  noLabel,
}: {
  value: boolean;
  yesLabel: string;
  noLabel: string;
}) {
  return (
    <span
      className={
        value
          ? "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800"
          : "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700"
      }
    >
      {value ? yesLabel : noLabel}
    </span>
  );
}

// ── Security posture card ─────────────────────────────────────────────────────

export type PostureCardProps = {
  icon: React.ElementType;
  label: string;
  status: boolean | null;
  detail: string;
  activeLabel: string;
  inactiveLabel: string;
  unknownLabel: string;
};

export function SecurityPostureCard({
  icon: Icon,
  label,
  status,
  detail,
  activeLabel,
  inactiveLabel,
  unknownLabel,
}: PostureCardProps) {
  const borderColor =
    status === true
      ? "border-l-emerald-500"
      : status === false
        ? "border-l-rose-400"
        : "border-l-[#c7c4d8]";
  const iconColor =
    status === true
      ? "text-emerald-600"
      : status === false
        ? "text-rose-500"
        : "text-[#777587]";

  return (
    <div
      className={`border-l-4 ${borderColor} rounded-lg border border-[#c7c4d8] bg-[#f5f2ff]/60 px-4 py-3`}
    >
      <div className="mb-1 flex items-center gap-2">
        <Icon size={16} className={iconColor} aria-hidden="true" />
        <p className="text-sm font-semibold text-[#1b1b24]">{label}</p>
        {status !== null && (
          <span
            className={
              status
                ? "ml-auto text-[10px] font-bold tracking-wider text-emerald-700 uppercase"
                : "ml-auto text-[10px] font-bold tracking-wider text-rose-600 uppercase"
            }
          >
            {status ? activeLabel : inactiveLabel}
          </span>
        )}
        {status === null && (
          <span className="ml-auto text-[10px] font-bold tracking-wider text-[#777587] uppercase">
            {unknownLabel}
          </span>
        )}
      </div>
      <p className="text-xs text-[#464555]">{detail}</p>
    </div>
  );
}

// ── Audit event preview ───────────────────────────────────────────────────────

export function AuditEventPreview({ event }: { event: AuditEvent }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-[#e4e1ee] bg-[#f5f2ff]/40 px-4 py-3">
      <ClipboardList
        size={16}
        className="mt-0.5 shrink-0 text-[#5d58a8]"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-[#1b1b24]">
          {event.summary}
        </p>
        <p className="text-xs text-[#464555]">
          {event.actor_email ?? "System"} &middot;{" "}
          {formatTimestamp(event.created_at)}
        </p>
      </div>
    </div>
  );
}

// ── Login policy form schema ──────────────────────────────────────────────────

export const loginPolicySchema = z.object({
  domainAllowlist: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
  sessionTimeoutHours: z.string(),
  ssoRequired: z.boolean(),
  inviteOnly: z.boolean(),
  mfaRequired: z.boolean(),
});

export type LoginPolicyFormValues = z.infer<typeof loginPolicySchema>;

export type SecuritySession = ReturnType<
  typeof useAuthSession
>["state"]["session"];
