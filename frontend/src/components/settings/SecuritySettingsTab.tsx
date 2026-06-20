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
import { useTranslations } from "next-intl";
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

function DeploymentControlledBadge({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600"
      aria-label="Deployment-controlled"
    >
      {label}
    </span>
  );
}

function UnavailableRow({
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

function BoolBadge({
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

type PostureCardProps = {
  icon: React.ElementType;
  label: string;
  status: boolean | null;
  detail: string;
  activeLabel: string;
  inactiveLabel: string;
  unknownLabel: string;
};

function SecurityPostureCard({
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

// ── Role capability key maps ──────────────────────────────────────────────────

type RoleCapKey =
  | "documentAccess"
  | "collectionAccess"
  | "evaluationAccess"
  | "agenticAccess"
  | "mcpAccess"
  | "adminControls";

const ROLE_CAP_KEYS: RoleCapKey[] = [
  "documentAccess",
  "collectionAccess",
  "evaluationAccess",
  "agenticAccess",
  "mcpAccess",
  "adminControls",
];

const ROLE_CAP_LABEL_KEYS: Record<RoleCapKey, string> = {
  documentAccess: "capDocumentAccess",
  collectionAccess: "capCollectionAccess",
  evaluationAccess: "capEvaluationAccess",
  agenticAccess: "capAgenticAccess",
  mcpAccess: "capMcpAccess",
  adminControls: "capAdminControls",
};

const ROLE_CAP_DESC_KEYS: Record<AppRole, Record<RoleCapKey, string>> = {
  owner: {
    documentAccess: "ownerDocument",
    collectionAccess: "ownerCollection",
    evaluationAccess: "ownerEvaluation",
    agenticAccess: "ownerAgentic",
    mcpAccess: "ownerMcp",
    adminControls: "ownerAdmin",
  },
  admin: {
    documentAccess: "adminDocument",
    collectionAccess: "adminCollection",
    evaluationAccess: "adminEvaluation",
    agenticAccess: "adminAgentic",
    mcpAccess: "adminMcp",
    adminControls: "adminAdminControls",
  },
  member: {
    documentAccess: "memberDocument",
    collectionAccess: "memberCollection",
    evaluationAccess: "memberEvaluation",
    agenticAccess: "memberAgentic",
    mcpAccess: "memberMcp",
    adminControls: "memberAdmin",
  },
  viewer: {
    documentAccess: "viewerDocument",
    collectionAccess: "viewerCollection",
    evaluationAccess: "viewerEvaluation",
    agenticAccess: "viewerAgentic",
    mcpAccess: "viewerMcp",
    adminControls: "viewerAdmin",
  },
  reviewer: {
    documentAccess: "reviewerDocument",
    collectionAccess: "reviewerCollection",
    evaluationAccess: "reviewerEvaluation",
    agenticAccess: "reviewerAgentic",
    mcpAccess: "reviewerMcp",
    adminControls: "reviewerAdmin",
  },
  developer: {
    documentAccess: "developerDocument",
    collectionAccess: "developerCollection",
    evaluationAccess: "developerEvaluation",
    agenticAccess: "developerAgentic",
    mcpAccess: "developerMcp",
    adminControls: "developerAdmin",
  },
  security_admin: {
    documentAccess: "securityAdminDocument",
    collectionAccess: "securityAdminCollection",
    evaluationAccess: "securityAdminEvaluation",
    agenticAccess: "securityAdminAgentic",
    mcpAccess: "securityAdminMcp",
    adminControls: "securityAdminAdminControls",
  },
  billing_admin: {
    documentAccess: "billingAdminDocument",
    collectionAccess: "billingAdminCollection",
    evaluationAccess: "billingAdminEvaluation",
    agenticAccess: "billingAdminAgentic",
    mcpAccess: "billingAdminMcp",
    adminControls: "billingAdminAdminControls",
  },
};

// ── Main component ────────────────────────────────────────────────────────────

export function SecuritySettingsTab() {
  const t = useTranslations("settings.security");
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
        label: t("auth.authProvider"),
        value: formatAuthProvider(config.authProviderRaw),
        isBoolean: false,
      },
      {
        label: t("auth.email"),
        value: session?.email ?? t("auth.unknown"),
        isBoolean: false,
      },
      {
        label: t("auth.role"),
        value: session?.role ?? t("auth.unknown"),
        isBoolean: false,
      },
      {
        label: t("auth.accessTokenAttached"),
        value: session?.accessToken ? t("auth.yes") : t("auth.no"),
        isBoolean: true,
      },
      {
        label: t("auth.refreshCookie"),
        value: t("auth.refreshCookieValue"),
        isBoolean: false,
      },
      {
        label: t("auth.sessionExpiry"),
        value: formatExpiryMs(sessionExpiryMs),
        isBoolean: false,
      },
      {
        label: t("auth.organizationId"),
        value: session?.organizationId ?? t("auth.notAssigned"),
        isBoolean: false,
      },
    ],
    [
      t,
      config.authProviderRaw,
      session?.email,
      session?.role,
      session?.accessToken,
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
      setRevokeState({ tone: "success", message: t("sessions.revoked") });
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
        message: t("sessions.allRevoked"),
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
        message: t("loginPolicy.saved"),
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
        label: t("posture.promptInjection"),
        status: p?.prompt_injection_protection ?? null,
        detail: t("posture.promptInjectionDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: BadgeCheck,
        label: t("posture.citationValidation"),
        status: p?.citation_validation ?? null,
        detail: t("posture.citationValidationDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: Lock,
        label: t("posture.tenantIsolation"),
        status: p?.tenant_isolation ?? null,
        detail: t("posture.tenantIsolationDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: FileSearch,
        label: t("posture.outputValidation"),
        status: p?.output_validation ?? null,
        detail: t("posture.outputValidationDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: Bot,
        label: t("posture.toolPolicy"),
        status: p?.tool_policy_enforced ?? null,
        detail: t("posture.toolPolicyDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
    ];
  }, [postureQuery.data, t]);

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
          <SectionHeader icon={ShieldCheck} title={t("auth.title")} />
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
                    <BoolBadge
                      value={fact.value === t("auth.yes")}
                      yesLabel={t("auth.yes")}
                      noLabel={t("auth.no")}
                    />
                  ) : (
                    <span className="text-sm text-[#1b1b24]">{fact.value}</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-[#777587]">{t("auth.tokenNote")}</p>
        </section>

        {/* 2. Active Sessions */}
        <section
          className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
          aria-label="Active sessions section"
        >
          <SectionHeader
            icon={Users}
            title={t("sessions.title")}
            badge={
              !capabilities.sessionsEnabled && (
                <DeploymentControlledBadge label={t("deploymentControlled")} />
              )
            }
          />

          {!capabilities.sessionsEnabled ? (
            <p className="text-sm text-[#777587]">
              {t("sessions.unavailable")}
            </p>
          ) : sessionsQuery.isLoading ? (
            <LoadingState compact title={t("sessions.loading")} />
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
                title={t("sessions.restrictedTitle")}
                description={t("sessions.restrictedDesc")}
                backHref="/dashboard"
                backLabel={t("backToDashboard")}
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
                      <th className="px-4 py-3">{t("sessions.device")}</th>
                      <th className="px-4 py-3">{t("sessions.location")}</th>
                      <th className="px-4 py-3">{t("sessions.lastActive")}</th>
                      <th className="px-4 py-3 text-right">
                        {t("sessions.action")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e4e1ee]">
                    {(sessionsQuery.data ?? []).length === 0 && (
                      <tr>
                        <td
                          colSpan={4}
                          className="px-4 py-4 text-center text-sm text-[#777587]"
                        >
                          {t("sessions.noSessions")}
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
                              {t("sessions.current")}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-[#464555]">
                          {s.location ?? t("sessions.unknown")}
                        </td>
                        <td className="px-4 py-3 text-[#464555]">
                          {formatTimestamp(s.last_active_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {s.is_current ? (
                            <span className="text-xs text-[#777587]">
                              {t("sessions.thisDevice")}
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
                              {revokingId === s.id
                                ? t("sessions.revoking")
                                : t("sessions.revoke")}
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
                        ? t("sessions.revokingAll")
                        : t("sessions.revokeAll")}
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
            title={t("loginPolicy.title")}
            badge={
              !capabilities.loginPolicyEnabled && (
                <DeploymentControlledBadge label={t("deploymentControlled")} />
              )
            }
          />

          {/* Change password link */}
          <div className="mb-6">
            {changePasswordUrl ? (
              <a
                href={changePasswordUrl}
                className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
              >
                {t("loginPolicy.changePassword")}
              </a>
            ) : (
              <UnavailableRow
                label={t("loginPolicy.changePasswordUnavailableLabel")}
                description={t("loginPolicy.changePasswordUnavailableDesc")}
                notAvailableMsg={t("notAvailableMsg")}
                unavailableLabel={t("unavailable")}
              />
            )}
          </div>

          {!capabilities.loginPolicyEnabled ? (
            <p className="text-sm text-[#777587]">
              {t("loginPolicy.unavailable")}
            </p>
          ) : !isAdmin ? (
            <ForbiddenState
              compact
              title={t("loginPolicy.restrictedTitle")}
              description={t("loginPolicy.restrictedDesc")}
              backHref="/dashboard"
              backLabel={t("backToDashboard")}
            />
          ) : loginPolicyQuery.isLoading ? (
            <LoadingState compact title={t("loginPolicy.loading")} />
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
                    {t("loginPolicy.domainAllowlist")}
                  </FieldLabel>
                  <input
                    id="sec-domain-allowlist"
                    {...loginPolicyForm.register("domainAllowlist")}
                    placeholder="example.com, partner.org"
                    className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                  <p className="text-xs text-[#777587]">
                    {t("loginPolicy.domainAllowlistHint")}
                  </p>
                </div>

                <div className="space-y-1">
                  <FieldLabel htmlFor="sec-session-timeout">
                    {t("loginPolicy.sessionTimeout")}
                  </FieldLabel>
                  <select
                    id="sec-session-timeout"
                    {...loginPolicyForm.register("sessionTimeoutHours")}
                    className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  >
                    <option value="8">{t("loginPolicy.hours8")}</option>
                    <option value="24">{t("loginPolicy.hours24")}</option>
                    <option value="168">{t("loginPolicy.days7")}</option>
                    <option value="720">{t("loginPolicy.days30")}</option>
                  </select>
                  <p className="text-xs text-[#777587]">
                    {t("loginPolicy.sessionTimeoutHint")}
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
                      {t("loginPolicy.enforceSSO")}
                    </label>
                    <p className="text-xs text-[#464555]">
                      {t("loginPolicy.enforceSSODesc")}
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
                      {t("loginPolicy.inviteOnly")}
                    </label>
                    <p className="text-xs text-[#464555]">
                      {t("loginPolicy.inviteOnlyDesc")}
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
                      {t("loginPolicy.requireMFA")}
                    </label>
                    <p className="text-xs text-[#464555]">
                      {t("loginPolicy.requireMFADesc")}
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
                    ? t("saving")
                    : t("loginPolicy.savePolicy")}
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
          <SectionHeader icon={ShieldCheck} title={t("rolePolicy.title")} />

          <div className="mb-4 flex items-center gap-3">
            <span className="text-sm text-[#464555]">
              {t("rolePolicy.currentRole")}
            </span>
            <span className="rounded-full bg-[#e2dfff] px-3 py-1 text-sm font-bold text-[#3525cd] capitalize">
              {role ?? t("unknown")}
            </span>
          </div>

          {role ? (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {ROLE_CAP_KEYS.map((capKey) => (
                <div
                  key={capKey}
                  className="flex flex-col rounded-lg border border-[#ebe8f7] bg-[#f5f2ff]/40 px-4 py-3"
                >
                  <dt className="text-xs font-semibold tracking-widest text-[#464555] uppercase">
                    {t(`rolePolicy.${ROLE_CAP_LABEL_KEYS[capKey]}`)}
                  </dt>
                  <dd className="mt-1 text-sm text-[#1b1b24]">
                    {t(`rolePolicy.${ROLE_CAP_DESC_KEYS[role][capKey]}`)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-[#777587]">
              {t("rolePolicy.unavailable")}
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
            title={t("rateLimits.title")}
            badge={
              <DeploymentControlledBadge label={t("deploymentControlled")} />
            }
          />
          <p className="mb-4 text-sm text-[#777587]">{t("rateLimits.desc")}</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              {
                label: t("rateLimits.uploadRateLimit"),
                description: t("rateLimits.deploymentControlledValue"),
              },
              {
                label: t("rateLimits.chatRateLimit"),
                description: t("rateLimits.deploymentControlledValue"),
              },
              {
                label: t("rateLimits.deleteRateLimit"),
                description: t("rateLimits.deploymentControlledValue"),
              },
              {
                label: t("rateLimits.evalRateLimit"),
                description: t("rateLimits.deploymentControlledValue"),
              },
              {
                label: t("rateLimits.apiKeyRateLimit"),
                description: t("rateLimits.notYetAvailable"),
              },
              {
                label: t("rateLimits.agentRateLimit"),
                description: t("rateLimits.notYetAvailable"),
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
            title={t("posture.title")}
            badge={
              !capabilities.postureEnabled && (
                <DeploymentControlledBadge label={t("deploymentControlled")} />
              )
            }
          />

          {!capabilities.postureEnabled ? (
            <div className="space-y-3">
              {postureCards.map((card) => (
                <SecurityPostureCard key={card.label} {...card} />
              ))}
              <p className="pt-1 text-xs text-[#777587]">
                {t("posture.defaultNote")}
              </p>
            </div>
          ) : postureQuery.isLoading ? (
            <LoadingState compact title={t("posture.loading")} />
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
                  {t("posture.lastAudit", {
                    time: formatTimestamp(postureQuery.data.last_audit_at),
                  })}
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
            title={t("audit.title")}
            badge={
              !capabilities.auditEnabled && (
                <DeploymentControlledBadge label={t("deploymentControlled")} />
              )
            }
          />

          {!isAdmin ? (
            <p className="text-sm text-[#777587]">{t("audit.restricted")}</p>
          ) : !capabilities.auditEnabled ? (
            <p className="text-sm text-[#777587]">{t("audit.unavailable")}</p>
          ) : auditQuery.isLoading ? (
            <LoadingState compact title={t("audit.loading")} />
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
                <p className="text-sm text-[#777587]">{t("audit.noEvents")}</p>
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
                {t("audit.openAuditLogs")}
              </a>
            )}
            {auditExportUrl && isAdmin && (
              <a
                href={auditExportUrl}
                className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#f5f3ff]"
              >
                {t("audit.exportLog")}
              </a>
            )}
            {!auditPageUrl && !auditExportUrl && (
              <span className="text-xs text-[#777587]">
                {t("audit.noLinks")}
              </span>
            )}
          </div>
          <p className="mt-3 text-xs text-[#777587]">{t("audit.retention")}</p>
        </section>
      </div>
    </div>
  );
}
