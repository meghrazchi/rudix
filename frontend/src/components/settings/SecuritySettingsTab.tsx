"use client";

import {
  AlertTriangle,
  BadgeCheck,
  Bot,
  ClipboardList,
  FileSearch,
  Lock,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getSecurityCapabilities,
  getSessions,
  revokeSession,
  revokeAllOtherSessions,
  getLoginPolicy,
  updateLoginPolicy,
  getSecurityPosture,
  getRecentAuditEvents,
  type SecurityPosture,
  type AuditEvent,
} from "@/lib/api/security";
import { getJwtExpirationTimeMs } from "@/lib/api/request";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import type { AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";

// ── Helpers ───────────────────────────────────────────────────────────────────

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

function isAdminLike(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function formatAuthProvider(raw: string | undefined): string {
  if (!raw?.trim()) return "app";
  return raw
    .trim()
    .split(/[\s_-]+/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
    .join(" ");
}

function formatTimestamp(value: string | null | undefined): string {
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

function formatExpiryMs(ms: number | null): string {
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

function fromList(list: string[]): string {
  return list.join(", ");
}

function toList(csv: string): string[] {
  return csv
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function SectionHeader({
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

function DeploymentControlledBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600"
      aria-label="Deployment-controlled"
    >
      Deployment-controlled
    </span>
  );
}

function UnavailableRow({
  label,
  description,
}: {
  label: string;
  description?: string;
}) {
  return (
    <div
      className="flex items-start justify-between gap-4 rounded-xl border border-dashed border-[#c7c4d8] px-4 py-3 opacity-70"
      aria-label={`${label} unavailable`}
    >
      <div>
        <p className="text-sm font-semibold text-[#1b1b24]">{label}</p>
        {description && <p className="text-xs text-[#464555]">{description}</p>}
        <p className="mt-1 text-xs text-[#777587]">
          Not available — deployment-controlled.
        </p>
      </div>
      <span className="shrink-0 rounded-xl border border-dashed border-[#c7c4d8] px-3 py-1.5 text-sm text-[#777587]">
        Unavailable
      </span>
    </div>
  );
}

type SaveState = { tone: "success" | "error"; message: string } | null;

function SaveFeedback({ state }: { state: SaveState }) {
  if (!state) return null;
  const cls =
    state.tone === "success"
      ? "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
      : "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
  return <p className={cls}>{state.message}</p>;
}

function ToggleSwitch({
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

function FieldLabel({
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

function BoolBadge({ value }: { value: boolean }) {
  return (
    <span
      className={
        value
          ? "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800"
          : "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700"
      }
    >
      {value ? "Yes" : "No"}
    </span>
  );
}

// ── Security posture card ─────────────────────────────────────────────────────

type PostureCardProps = {
  icon: React.ElementType;
  label: string;
  status: boolean | null;
  detail: string;
};

function SecurityPostureCard({
  icon: Icon,
  label,
  status,
  detail,
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
            {status ? "Active" : "Inactive"}
          </span>
        )}
        {status === null && (
          <span className="ml-auto text-[10px] font-bold tracking-wider text-[#777587] uppercase">
            Unknown
          </span>
        )}
      </div>
      <p className="text-xs text-[#464555]">{detail}</p>
    </div>
  );
}

// ── Audit event preview ───────────────────────────────────────────────────────

function AuditEventPreview({ event }: { event: AuditEvent }) {
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

const loginPolicySchema = z.object({
  domainAllowlist: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
  sessionTimeoutHours: z.string(),
  ssoRequired: z.boolean(),
  inviteOnly: z.boolean(),
  mfaRequired: z.boolean(),
});

type LoginPolicyFormValues = z.infer<typeof loginPolicySchema>;

// ── Role/access summary ───────────────────────────────────────────────────────

const ROLE_CAPABILITIES: Record<
  AppRole,
  { label: string; description: string }[]
> = {
  owner: [
    { label: "Document access", description: "Full read/write" },
    { label: "Collection access", description: "Full read/write" },
    { label: "Evaluation access", description: "Enabled" },
    { label: "Agentic access", description: "Enabled" },
    { label: "MCP access", description: "Enabled" },
    { label: "Admin controls", description: "Full access" },
  ],
  admin: [
    { label: "Document access", description: "Full read/write" },
    { label: "Collection access", description: "Full read/write" },
    { label: "Evaluation access", description: "Enabled" },
    { label: "Agentic access", description: "Enabled" },
    { label: "MCP access", description: "Enabled" },
    { label: "Admin controls", description: "Org settings only" },
  ],
  member: [
    { label: "Document access", description: "Read/write per collection" },
    { label: "Collection access", description: "Assigned collections" },
    { label: "Evaluation access", description: "If org-enabled" },
    { label: "Agentic access", description: "If org-enabled" },
    { label: "MCP access", description: "If org-enabled" },
    { label: "Admin controls", description: "None" },
  ],
  viewer: [
    { label: "Document access", description: "Read-only" },
    { label: "Collection access", description: "Assigned collections" },
    { label: "Evaluation access", description: "Read-only" },
    { label: "Agentic access", description: "None" },
    { label: "MCP access", description: "None" },
    { label: "Admin controls", description: "None" },
  ],
};

// ── Main component ────────────────────────────────────────────────────────────

export function SecuritySettingsTab() {
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role ?? null;
  const isAdmin = isAdminLike(role);

  const capabilities = useMemo(() => getSecurityCapabilities(), []);
  const config = useMemo(() => getFrontendRuntimeConfig(), []);

  const changePasswordUrl = trimToNull(
    process.env.NEXT_PUBLIC_SECURITY_CHANGE_PASSWORD_URL,
  );
  const auditPageUrl = trimToNull(process.env.NEXT_PUBLIC_AUDIT_PAGE_URL);
  const auditExportUrl = trimToNull(
    process.env.NEXT_PUBLIC_SECURITY_AUDIT_EXPORT_URL,
  );

  // ── Auth diagnostics ────────────────────────────────────────────────────────

  const sessionExpiryMs = getJwtExpirationTimeMs(session?.accessToken ?? null);

  const authFacts = useMemo(
    () => [
      {
        label: "Auth provider",
        value: formatAuthProvider(config.authProviderRaw),
        isBoolean: false,
      },
      {
        label: "Email",
        value: session?.email ?? "Unknown",
        isBoolean: false,
      },
      {
        label: "Role",
        value: session?.role ?? "Unknown",
        isBoolean: false,
      },
      {
        label: "Access token attached",
        value: session?.accessToken ? "Yes" : "No",
        isBoolean: true,
      },
      {
        label: "Refresh token available",
        value: session?.refreshToken ? "Yes" : "No",
        isBoolean: true,
      },
      {
        label: "Session expiry",
        value: formatExpiryMs(sessionExpiryMs),
        isBoolean: false,
      },
      {
        label: "Organization ID",
        value: session?.organizationId ?? "Not assigned",
        isBoolean: false,
      },
    ],
    [
      config.authProviderRaw,
      session?.email,
      session?.role,
      session?.accessToken,
      session?.refreshToken,
      session?.organizationId,
      sessionExpiryMs,
    ],
  );

  // ── Active sessions ─────────────────────────────────────────────────────────

  const sessionsQuery = useQuery({
    queryKey: ["security", "sessions"],
    queryFn: getSessions,
    enabled: capabilities.sessionsEnabled,
    retry: false,
  });

  const [revokeState, setRevokeState] = useState<SaveState>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const revokeSessionMutation = useMutation({
    mutationFn: (sessionId: string) => revokeSession(sessionId),
    onSuccess: () => {
      void sessionsQuery.refetch();
      setRevokeState({ tone: "success", message: "Session revoked." });
      setRevokingId(null);
    },
    onError: (error) => {
      setRevokeState({ tone: "error", message: getApiErrorMessage(error) });
      setRevokingId(null);
    },
  });

  const revokeAllMutation = useMutation({
    mutationFn: revokeAllOtherSessions,
    onSuccess: () => {
      void sessionsQuery.refetch();
      setRevokeState({
        tone: "success",
        message: "All other sessions revoked.",
      });
    },
    onError: (error) => {
      setRevokeState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  function handleRevokeSession(sessionId: string, device: string): void {
    const confirmed = window.confirm(
      `Revoke session for "${device}"? That device will be signed out immediately.`,
    );
    if (!confirmed) return;
    setRevokeState(null);
    setRevokingId(sessionId);
    revokeSessionMutation.mutate(sessionId);
  }

  function handleRevokeAll(): void {
    const confirmed = window.confirm(
      "Revoke all other active sessions? Every device except the current one will be signed out immediately.",
    );
    if (!confirmed) return;
    setRevokeState(null);
    revokeAllMutation.mutate();
  }

  // ── Login policy ────────────────────────────────────────────────────────────

  const [loginPolicySaveState, setLoginPolicySaveState] =
    useState<SaveState>(null);

  const defaultLoginPolicyValues: LoginPolicyFormValues = {
    domainAllowlist: "",
    sessionTimeoutHours: "24",
    ssoRequired: false,
    inviteOnly: false,
    mfaRequired: false,
  };

  const loginPolicyForm = useForm<LoginPolicyFormValues>({
    resolver: zodResolver(loginPolicySchema),
    defaultValues: defaultLoginPolicyValues,
    mode: "onSubmit",
  });

  const loginPolicyQuery = useQuery({
    queryKey: ["security", "login-policy"],
    queryFn: getLoginPolicy,
    enabled: capabilities.loginPolicyEnabled && isAdmin,
    retry: false,
  });

  useMemo(() => {
    if (!loginPolicyQuery.data) return;
    loginPolicyForm.reset({
      domainAllowlist: fromList(loginPolicyQuery.data.domain_allowlist),
      sessionTimeoutHours:
        loginPolicyQuery.data.session_timeout_hours?.toString() ?? "24",
      ssoRequired: loginPolicyQuery.data.sso_required,
      inviteOnly: loginPolicyQuery.data.invite_only,
      mfaRequired: loginPolicyQuery.data.mfa_required,
    });
  }, [loginPolicyQuery.data, loginPolicyForm]);

  const loginPolicySaveMutation = useMutation({
    mutationFn: (values: LoginPolicyFormValues) =>
      updateLoginPolicy({
        domain_allowlist: toList(values.domainAllowlist),
        session_timeout_hours: values.sessionTimeoutHours
          ? Number(values.sessionTimeoutHours)
          : null,
        sso_required: values.ssoRequired,
        invite_only: values.inviteOnly,
        mfa_required: values.mfaRequired,
      }),
    onSuccess: () => {
      setLoginPolicySaveState({
        tone: "success",
        message: "Login policy saved.",
      });
    },
    onError: (error) => {
      setLoginPolicySaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveLoginPolicy(): Promise<void> {
    setLoginPolicySaveState(null);
    const valid = await loginPolicyForm.trigger();
    if (!valid) return;
    await loginPolicySaveMutation.mutateAsync(loginPolicyForm.getValues());
  }

  const watchedSsoRequired = loginPolicyForm.watch("ssoRequired");
  const watchedInviteOnly = loginPolicyForm.watch("inviteOnly");
  const watchedMfaRequired = loginPolicyForm.watch("mfaRequired");

  // ── Security posture ────────────────────────────────────────────────────────

  const postureQuery = useQuery({
    queryKey: ["security", "posture"],
    queryFn: getSecurityPosture,
    enabled: capabilities.postureEnabled,
    retry: false,
  });

  const postureCards = useMemo((): PostureCardProps[] => {
    const p = postureQuery.data;
    return [
      {
        icon: ShieldAlert,
        label: "Prompt Injection Protection",
        status: p?.prompt_injection_protection ?? null,
        detail: "Monitors and filters adversarial prompt inputs.",
      },
      {
        icon: BadgeCheck,
        label: "Citation Validation",
        status: p?.citation_validation ?? null,
        detail: "Verifies source veracity for all retrieval pipelines.",
      },
      {
        icon: Lock,
        label: "Tenant Isolation",
        status: p?.tenant_isolation ?? null,
        detail: "Encryption at rest with per-tenant managed keys.",
      },
      {
        icon: FileSearch,
        label: "Output Validation",
        status: p?.output_validation ?? null,
        detail: "Validates LLM outputs before returning to clients.",
      },
      {
        icon: Bot,
        label: "Tool/MCP Policy",
        status: p?.tool_policy_enforced ?? null,
        detail: "Enforces allow-list for agentic tool and MCP calls.",
      },
    ];
  }, [postureQuery.data]);

  // ── Recent audit events ─────────────────────────────────────────────────────

  const auditQuery = useQuery({
    queryKey: ["security", "audit"],
    queryFn: getRecentAuditEvents,
    enabled: capabilities.auditEnabled && isAdmin,
    retry: false,
  });

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
      {/* ── Left column ── */}
      <div className="space-y-6 lg:col-span-8">
        {/* 1. Auth Diagnostics */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Authentication diagnostics section"
        >
          <SectionHeader icon={ShieldCheck} title="Authentication & Session" />
          <dl className="space-y-3">
            {authFacts.map((fact) => (
              <div
                key={fact.label}
                className="flex items-center justify-between gap-4 rounded-lg border border-[#ebe8f7] px-4 py-2"
              >
                <dt className="text-sm font-semibold text-[#5c5871]">
                  {fact.label}
                </dt>
                <dd>
                  {fact.isBoolean ? (
                    <BoolBadge value={fact.value === "Yes"} />
                  ) : (
                    <span className="text-sm text-[#1b1b24]">{fact.value}</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-[#777587]">
            Token values are never displayed. Only safe metadata is shown.
          </p>
        </section>

        {/* 2. Active Sessions */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Active sessions section"
        >
          <SectionHeader
            icon={Users}
            title="Active Sessions"
            badge={
              !capabilities.sessionsEnabled && <DeploymentControlledBadge />
            }
          />

          {!capabilities.sessionsEnabled ? (
            <p className="text-sm text-[#777587]">
              Session management is not available — deployment-controlled.
            </p>
          ) : sessionsQuery.isLoading ? (
            <LoadingState compact title="Loading sessions..." />
          ) : sessionsQuery.isError ? (
            isApiClientError(sessionsQuery.error) &&
            sessionsQuery.error.status === 429 ? (
              <RateLimitState
                compact
                onRetry={() => {
                  void sessionsQuery.refetch();
                }}
              />
            ) : isApiClientError(sessionsQuery.error) &&
              sessionsQuery.error.status === 403 ? (
              <ForbiddenState
                compact
                title="Sessions restricted"
                description="You do not have permission to view active sessions."
                backHref="/dashboard"
                backLabel="Back to dashboard"
              />
            ) : (
              <ErrorState
                compact
                error={sessionsQuery.error}
                description={getApiErrorMessage(sessionsQuery.error)}
                onRetry={() => {
                  void sessionsQuery.refetch();
                }}
              />
            )
          ) : (
            <>
              <div className="overflow-x-auto rounded-xl border border-[#e4e1ee]">
                <table className="w-full text-left text-sm">
                  <thead className="bg-[#f5f2ff] text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                    <tr>
                      <th className="px-4 py-3">Device</th>
                      <th className="px-4 py-3">Location</th>
                      <th className="px-4 py-3">Last active</th>
                      <th className="px-4 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e4e1ee]">
                    {(sessionsQuery.data ?? []).length === 0 && (
                      <tr>
                        <td
                          colSpan={4}
                          className="px-4 py-4 text-center text-sm text-[#777587]"
                        >
                          No active sessions found.
                        </td>
                      </tr>
                    )}
                    {(sessionsQuery.data ?? []).map((s) => (
                      <tr
                        key={s.id}
                        className="transition-colors hover:bg-[#f5f2ff]/40"
                      >
                        <td className="px-4 py-3">
                          <span className="font-semibold text-[#1b1b24]">
                            {s.device}
                          </span>
                          {s.is_current && (
                            <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                              Current
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-[#464555]">
                          {s.location ?? "Unknown"}
                        </td>
                        <td className="px-4 py-3 text-[#464555]">
                          {formatTimestamp(s.last_active_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {s.is_current ? (
                            <span className="text-xs text-[#777587]">
                              This device
                            </span>
                          ) : capabilities.revokeSessionEnabled ? (
                            <button
                              type="button"
                              disabled={
                                revokingId === s.id ||
                                revokeSessionMutation.isPending
                              }
                              onClick={() =>
                                handleRevokeSession(s.id, s.device)
                              }
                              className="text-sm font-semibold text-[#777587] transition-colors hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {revokingId === s.id ? "Revoking…" : "Revoke"}
                            </button>
                          ) : (
                            <span className="text-xs text-[#777587]">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {capabilities.revokeAllSessionsEnabled &&
                (sessionsQuery.data?.length ?? 0) > 1 && (
                  <div className="mt-4 flex items-center justify-between gap-4">
                    <SaveFeedback state={revokeState} />
                    <button
                      type="button"
                      disabled={
                        revokeAllMutation.isPending ||
                        revokeSessionMutation.isPending
                      }
                      onClick={handleRevokeAll}
                      className="ml-auto rounded-xl border border-rose-200 px-4 py-2 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {revokeAllMutation.isPending
                        ? "Revoking all…"
                        : "Revoke all other sessions"}
                    </button>
                  </div>
                )}

              {revokeState && !capabilities.revokeAllSessionsEnabled && (
                <div className="mt-3">
                  <SaveFeedback state={revokeState} />
                </div>
              )}
            </>
          )}
        </section>

        {/* 3. Login Policy */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Login policy section"
        >
          <SectionHeader
            icon={SlidersHorizontal}
            title="Login & Authentication Policy"
            badge={
              !capabilities.loginPolicyEnabled && <DeploymentControlledBadge />
            }
          />

          {/* Change password link */}
          <div className="mb-6">
            {changePasswordUrl ? (
              <a
                href={changePasswordUrl}
                className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
              >
                Change password
              </a>
            ) : (
              <UnavailableRow
                label="Change password"
                description="Password change is managed by your identity provider."
              />
            )}
          </div>

          {!capabilities.loginPolicyEnabled ? (
            <p className="text-sm text-[#777587]">
              Login policy settings are not available — deployment-controlled.
            </p>
          ) : !isAdmin ? (
            <ForbiddenState
              compact
              title="Login policy restricted"
              description="Login policy can only be viewed and edited by owner/admin roles."
              backHref="/dashboard"
              backLabel="Back to dashboard"
            />
          ) : loginPolicyQuery.isLoading ? (
            <LoadingState compact title="Loading login policy..." />
          ) : loginPolicyQuery.isError ? (
            isApiClientError(loginPolicyQuery.error) &&
            loginPolicyQuery.error.status === 429 ? (
              <RateLimitState
                compact
                onRetry={() => {
                  void loginPolicyQuery.refetch();
                }}
              />
            ) : (
              <ErrorState
                compact
                error={loginPolicyQuery.error}
                description={getApiErrorMessage(loginPolicyQuery.error)}
                onRetry={() => {
                  void loginPolicyQuery.refetch();
                }}
              />
            )
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-1">
                  <FieldLabel htmlFor="sec-domain-allowlist">
                    Domain Allowlist
                  </FieldLabel>
                  <input
                    id="sec-domain-allowlist"
                    {...loginPolicyForm.register("domainAllowlist")}
                    placeholder="example.com, partner.org"
                    className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                  <p className="text-xs text-[#777587]">
                    Comma-separated allowed email domains.
                  </p>
                </div>

                <div className="space-y-1">
                  <FieldLabel htmlFor="sec-session-timeout">
                    Session Timeout
                  </FieldLabel>
                  <select
                    id="sec-session-timeout"
                    {...loginPolicyForm.register("sessionTimeoutHours")}
                    className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  >
                    <option value="8">8 hours</option>
                    <option value="24">24 hours</option>
                    <option value="168">7 days</option>
                    <option value="720">30 days</option>
                  </select>
                  <p className="text-xs text-[#777587]">
                    Users are signed out after this period of inactivity.
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                  <div>
                    <label
                      htmlFor="sec-sso-required"
                      className="text-sm font-semibold text-[#1b1b24]"
                    >
                      Enforce SSO
                    </label>
                    <p className="text-xs text-[#464555]">
                      Disable password logins for the organization.
                    </p>
                  </div>
                  <ToggleSwitch
                    id="sec-sso-required"
                    checked={watchedSsoRequired}
                    onChange={(v) =>
                      loginPolicyForm.setValue("ssoRequired", v, {
                        shouldDirty: true,
                      })
                    }
                  />
                </div>

                <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                  <div>
                    <label
                      htmlFor="sec-invite-only"
                      className="text-sm font-semibold text-[#1b1b24]"
                    >
                      Invite-only access
                    </label>
                    <p className="text-xs text-[#464555]">
                      Restrict new members to invited users only.
                    </p>
                  </div>
                  <ToggleSwitch
                    id="sec-invite-only"
                    checked={watchedInviteOnly}
                    onChange={(v) =>
                      loginPolicyForm.setValue("inviteOnly", v, {
                        shouldDirty: true,
                      })
                    }
                  />
                </div>

                <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                  <div>
                    <label
                      htmlFor="sec-mfa-required"
                      className="text-sm font-semibold text-[#1b1b24]"
                    >
                      Require MFA
                    </label>
                    <p className="text-xs text-[#464555]">
                      Enforce TOTP or hardware key for all members.
                    </p>
                  </div>
                  <ToggleSwitch
                    id="sec-mfa-required"
                    checked={watchedMfaRequired}
                    onChange={(v) =>
                      loginPolicyForm.setValue("mfaRequired", v, {
                        shouldDirty: true,
                      })
                    }
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3">
                <SaveFeedback state={loginPolicySaveState} />
                <button
                  type="button"
                  onClick={() => {
                    void handleSaveLoginPolicy();
                  }}
                  disabled={loginPolicySaveMutation.isPending}
                  className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loginPolicySaveMutation.isPending
                    ? "Saving…"
                    : "Save policy"}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* 4. Role & Access Policy */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Role and access policy section"
        >
          <SectionHeader icon={ShieldCheck} title="Role & Access Policy" />

          <div className="mb-4 flex items-center gap-3">
            <span className="text-sm text-[#464555]">Current role:</span>
            <span className="rounded-full bg-[#e2dfff] px-3 py-1 text-sm font-bold text-[#3525cd] capitalize">
              {role ?? "Unknown"}
            </span>
          </div>

          {role ? (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {ROLE_CAPABILITIES[role].map((cap) => (
                <div
                  key={cap.label}
                  className="flex flex-col rounded-lg border border-[#ebe8f7] bg-[#f5f2ff]/40 px-4 py-3"
                >
                  <dt className="text-xs font-semibold tracking-widest text-[#464555] uppercase">
                    {cap.label}
                  </dt>
                  <dd className="mt-1 text-sm text-[#1b1b24]">
                    {cap.description}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-[#777587]">
              Role information unavailable.
            </p>
          )}
        </section>

        {/* 5. Rate Limits & Abuse Protection */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Rate limits section"
        >
          <SectionHeader
            icon={AlertTriangle}
            title="Rate Limits & Abuse Protection"
            badge={<DeploymentControlledBadge />}
          />
          <p className="mb-4 text-sm text-[#777587]">
            Rate limits are deployment-controlled and enforced server-side. The
            values below reflect the deployment defaults.
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              {
                label: "Upload rate limit",
                description: "Deployment-controlled",
              },
              {
                label: "Chat rate limit",
                description: "Deployment-controlled",
              },
              {
                label: "Delete rate limit",
                description: "Deployment-controlled",
              },
              {
                label: "Evaluation rate limit",
                description: "Deployment-controlled",
              },
              {
                label: "API key rate limit",
                description: "Not yet available",
              },
              {
                label: "Agent rate limit",
                description: "Not yet available",
              },
            ].map((row) => (
              <div
                key={row.label}
                className="flex items-center justify-between rounded-lg border border-dashed border-[#c7c4d8] px-4 py-3 opacity-80"
              >
                <span className="text-sm font-semibold text-[#1b1b24]">
                  {row.label}
                </span>
                <span className="text-xs text-[#777587]">
                  {row.description}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ── Right column ── */}
      <div className="space-y-6 lg:col-span-4">
        {/* 6. AI Safety Posture */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="AI safety posture section"
        >
          <SectionHeader
            icon={Bot}
            title="AI Safety Posture"
            badge={
              !capabilities.postureEnabled && <DeploymentControlledBadge />
            }
          />

          {!capabilities.postureEnabled ? (
            <div className="space-y-3">
              {postureCards.map((card) => (
                <SecurityPostureCard key={card.label} {...card} />
              ))}
              <p className="pt-1 text-xs text-[#777587]">
                Live posture data is not available — deployment-controlled.
                Showing default configuration.
              </p>
            </div>
          ) : postureQuery.isLoading ? (
            <LoadingState compact title="Loading posture..." />
          ) : postureQuery.isError ? (
            <ErrorState
              compact
              error={postureQuery.error}
              description={getApiErrorMessage(postureQuery.error)}
              onRetry={() => {
                void postureQuery.refetch();
              }}
            />
          ) : (
            <div className="space-y-3">
              {postureCards.map((card) => (
                <SecurityPostureCard key={card.label} {...card} />
              ))}
              {postureQuery.data?.last_audit_at && (
                <p className="pt-1 text-xs text-[#777587]">
                  Last audit: {formatTimestamp(postureQuery.data.last_audit_at)}
                </p>
              )}
            </div>
          )}
        </section>

        {/* 7. Audit Log */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Audit log section"
        >
          <SectionHeader
            icon={ClipboardList}
            title="Audit Log"
            badge={!capabilities.auditEnabled && <DeploymentControlledBadge />}
          />

          {!isAdmin ? (
            <p className="text-sm text-[#777587]">
              Audit log access is restricted to owner/admin roles.
            </p>
          ) : !capabilities.auditEnabled ? (
            <p className="text-sm text-[#777587]">
              Audit log is not available — deployment-controlled.
            </p>
          ) : auditQuery.isLoading ? (
            <LoadingState compact title="Loading audit events..." />
          ) : auditQuery.isError ? (
            <ErrorState
              compact
              error={auditQuery.error}
              description={getApiErrorMessage(auditQuery.error)}
              onRetry={() => {
                void auditQuery.refetch();
              }}
            />
          ) : (
            <div className="space-y-2">
              {(auditQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-[#777587]">
                  No recent security events.
                </p>
              ) : (
                (auditQuery.data ?? []).map((event) => (
                  <AuditEventPreview key={event.id} event={event} />
                ))
              )}
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            {auditPageUrl && (
              <a
                href={auditPageUrl}
                className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
              >
                Open audit logs
              </a>
            )}
            {auditExportUrl && isAdmin && (
              <a
                href={auditExportUrl}
                className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#f5f3ff]"
              >
                Export log
              </a>
            )}
            {!auditPageUrl && !auditExportUrl && (
              <span className="text-xs text-[#777587]">
                No audit log links configured.
              </span>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
