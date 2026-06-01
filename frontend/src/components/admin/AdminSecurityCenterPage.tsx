"use client";

import {
  AlertTriangle,
  CheckCircle2,
  KeyRound,
  Link2,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import {
  listAuditLogs,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getOrganizationCapabilities,
  getOrganizationProfile,
  getOrganizationSettings,
} from "@/lib/api/organization";
import { getJwtExpirationTimeMs } from "@/lib/api/request";
import {
  getLoginPolicy,
  getSecurityCapabilities,
  getSecurityPosture,
  getSessions,
} from "@/lib/api/security";
import { getTeamCapabilities, listTeamMembers } from "@/lib/api/team";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage, resolveUsageDateRange } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { useAuthSession } from "@/lib/use-auth-session";

type WarningSeverity = "high" | "medium" | "low";

type SecurityWarning = {
  id: string;
  title: string;
  description: string;
  severity: WarningSeverity;
  href?: string;
};

type RecommendationItem = {
  id: string;
  title: string;
  description: string;
  href: string;
};

const AUDIT_PAGE_LIMIT = 100;

const AUDIT_HEALTH_RULES: Array<{
  key: string;
  label: string;
  matches: (action: string) => boolean;
}> = [
  {
    key: "auth-login-logout",
    label: "Login and logout",
    matches: (action) =>
      action.startsWith("auth.login.") || action.startsWith("auth.logout."),
  },
  {
    key: "token-refresh-failure",
    label: "Token refresh failures",
    matches: (action) => action === "auth.refresh.failed",
  },
  {
    key: "upload-delete",
    label: "Upload and delete",
    matches: (action) =>
      action.startsWith("document.upload.") ||
      action.startsWith("document.delete."),
  },
  {
    key: "policy-changes",
    label: "Policy changes",
    matches: (action) => action.includes("policy"),
  },
  {
    key: "chat-export-share",
    label: "Chat, export, and share",
    matches: (action) =>
      action.startsWith("chat.") ||
      action.includes("export") ||
      action.includes("share"),
  },
  {
    key: "api-key-webhook",
    label: "API key and webhook actions",
    matches: (action) =>
      action.includes("api_key") || action.includes("webhook"),
  },
  {
    key: "admin-changes",
    label: "Admin changes",
    matches: (action) => action.startsWith("admin."),
  },
];

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function isExternalHref(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return value;
  }
  return new Date(parsed).toLocaleString();
}

function formatSessionExpiry(ms: number | null): string {
  if (!ms) {
    return "Unknown";
  }
  const diff = ms - Date.now();
  if (diff <= 0) {
    return "Expired";
  }
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) {
    return `${minutes}m remaining`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h remaining`;
  }
  return `${Math.floor(hours / 24)}d remaining`;
}

function severityBadgeClass(severity: WarningSeverity): string {
  if (severity === "high") {
    return "bg-rose-100 text-rose-800";
  }
  if (severity === "medium") {
    return "bg-amber-100 text-amber-800";
  }
  return "bg-slate-200 text-slate-700";
}

function statusBadgeClass(status: "ok" | "warning" | "unknown"): string {
  if (status === "ok") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (status === "warning") {
    return "bg-amber-100 text-amber-800";
  }
  return "bg-slate-200 text-slate-700";
}

function summarizeRoles(
  members: Array<{ role: string }> | undefined,
  fallbackRole: string | null | undefined,
): string {
  if (!members || members.length === 0) {
    return fallbackRole ? `Current role: ${fallbackRole}` : "Not available";
  }

  const counts = {
    owner: 0,
    admin: 0,
    member: 0,
    viewer: 0,
  };

  for (const member of members) {
    if (member.role === "owner") {
      counts.owner += 1;
      continue;
    }
    if (member.role === "admin") {
      counts.admin += 1;
      continue;
    }
    if (member.role === "member") {
      counts.member += 1;
      continue;
    }
    if (member.role === "viewer") {
      counts.viewer += 1;
    }
  }

  return [
    `Owner ${counts.owner}`,
    `Admin ${counts.admin}`,
    `Member ${counts.member}`,
    `Viewer ${counts.viewer}`,
  ].join(" · ");
}

function summarizeAuditHealth(items: AuditLogListItemResponse[]): {
  failedCount: number;
  severeCount: number;
  missingControls: string[];
} {
  const failedCount = items.filter((item) => item.result === "failure").length;
  const severeCount = items.filter((item) => {
    const severity = typeof item.severity === "string" ? item.severity : "";
    const normalized = severity.trim().toLowerCase();
    return normalized === "high" || normalized === "critical";
  }).length;

  const missingControls = AUDIT_HEALTH_RULES.filter((rule) => {
    return !items.some((item) => rule.matches(item.action.toLowerCase()));
  }).map((rule) => rule.label);

  return { failedCount, severeCount, missingControls };
}

function buildWarnings(params: {
  loginPolicy: Awaited<ReturnType<typeof getLoginPolicy>> | undefined;
  posture: Awaited<ReturnType<typeof getSecurityPosture>> | undefined;
  organizationSettings:
    | Awaited<ReturnType<typeof getOrganizationSettings>>
    | undefined;
  auditItems: AuditLogListItemResponse[];
  missingAuditControls: string[];
  sessionsConfigured: boolean;
  apiKeysUrl: string | null;
  webhooksUrl: string | null;
}): SecurityWarning[] {
  const warnings: SecurityWarning[] = [];

  if (!params.sessionsConfigured) {
    warnings.push({
      id: "sessions-visibility-gap",
      title: "Session visibility is unavailable",
      description:
        "Active session telemetry is deployment-controlled. Enable the sessions endpoint for incident response coverage.",
      severity: "medium",
      href: "/settings?tab=security",
    });
  }

  if (params.loginPolicy) {
    if (!params.loginPolicy.mfa_required) {
      warnings.push({
        id: "mfa-disabled",
        title: "MFA is not required",
        description:
          "Require MFA for all privileged users to reduce account takeover risk.",
        severity: "high",
        href: "/settings?tab=security",
      });
    }
    if (!params.loginPolicy.sso_required) {
      warnings.push({
        id: "sso-optional",
        title: "SSO is optional",
        description:
          "If your organization has an identity provider, enforce SSO for centralized access revocation.",
        severity: "medium",
        href: "/settings?tab=security",
      });
    }
    if (params.loginPolicy.domain_allowlist.length === 0) {
      warnings.push({
        id: "domain-allowlist-empty",
        title: "No email domain restrictions",
        description:
          "No login domain allowlist is configured. Restrict domains if your policy requires controlled tenant access.",
        severity: "medium",
        href: "/settings?tab=organization",
      });
    }
    if (
      params.loginPolicy.session_timeout_hours == null ||
      params.loginPolicy.session_timeout_hours > 168
    ) {
      warnings.push({
        id: "session-timeout-weak",
        title: "Session timeout is not strict",
        description:
          "Set a bounded session timeout (for example 8h or 24h) for lower token persistence risk.",
        severity: "medium",
        href: "/settings?tab=security",
      });
    }
  }

  if (params.organizationSettings) {
    if (params.organizationSettings.retention_days == null) {
      warnings.push({
        id: "retention-unbounded",
        title: "No data retention limit configured",
        description:
          "Retention is unlimited. Define retention days to align audit and data lifecycle controls.",
        severity: "high",
        href: "/settings?tab=organization",
      });
    }
    if (params.organizationSettings.source_download === "all") {
      warnings.push({
        id: "source-download-open",
        title: "Source downloads allowed for all roles",
        description:
          "Allowing source downloads for all roles can increase document exfiltration risk.",
        severity: "medium",
        href: "/settings?tab=organization",
      });
    }
  }

  if (params.posture) {
    if (params.posture.prompt_injection_protection === false) {
      warnings.push({
        id: "prompt-injection-disabled",
        title: "Prompt-injection protection is inactive",
        description:
          "Enable guardrails for retrieval-side prompt injection defenses.",
        severity: "high",
      });
    }
    if (params.posture.citation_validation === false) {
      warnings.push({
        id: "citation-validation-disabled",
        title: "Citation validation is inactive",
        description:
          "Enable citation validation to reduce unsupported responses in regulated workflows.",
        severity: "high",
      });
    }
    if (params.posture.tenant_isolation === false) {
      warnings.push({
        id: "tenant-isolation-inactive",
        title: "Tenant isolation signal is inactive",
        description:
          "Tenant isolation must remain active to prevent cross-organization access exposure.",
        severity: "high",
      });
    }
    if (params.posture.output_validation === false) {
      warnings.push({
        id: "output-validation-disabled",
        title: "Output validation is inactive",
        description:
          "Enable output validation for safer generated answers and tool responses.",
        severity: "medium",
      });
    }
  }

  if (params.auditItems.length === 0) {
    warnings.push({
      id: "audit-events-empty",
      title: "No recent audit activity",
      description:
        "No events were found in the selected period. Verify auditing instrumentation and traffic assumptions.",
      severity: "medium",
      href: "/admin/audit-logs",
    });
  }

  if (params.missingAuditControls.length > 0) {
    warnings.push({
      id: "audit-control-gaps",
      title: "Audit control coverage has gaps",
      description: `No recent events detected for: ${params.missingAuditControls.join(", ")}.`,
      severity: "medium",
      href: "/admin/audit-logs",
    });
  }

  if (!params.apiKeysUrl) {
    warnings.push({
      id: "api-keys-control-missing",
      title: "API key control is not configured",
      description:
        "No API key management link is configured in this deployment. Add it when API key management is available.",
      severity: "low",
    });
  }

  if (!params.webhooksUrl) {
    warnings.push({
      id: "webhooks-control-missing",
      title: "Webhook control is not configured",
      description:
        "No webhook management link is configured in this deployment. Add it when webhook management is available.",
      severity: "low",
    });
  }

  return warnings;
}

function buildRecommendations(
  warnings: SecurityWarning[],
): RecommendationItem[] {
  const recommendations = new Map<string, RecommendationItem>();

  for (const warning of warnings) {
    if (!warning.href) {
      continue;
    }
    recommendations.set(warning.id, {
      id: warning.id,
      title: warning.title,
      description: warning.description,
      href: warning.href,
    });
  }

  if (!recommendations.has("audit-review")) {
    recommendations.set("audit-review", {
      id: "audit-review",
      title: "Review audit logs on a fixed cadence",
      description:
        "Use audit search and export to review access, policy changes, and privileged actions on a recurring schedule.",
      href: "/admin/audit-logs",
    });
  }

  return [...recommendations.values()];
}

function ActionLink({ href, label }: { href: string; label: string }) {
  if (isExternalHref(href)) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-1.5 text-xs font-semibold text-[#3525cd] hover:bg-[#f8f6ff]"
      >
        {label}
      </a>
    );
  }

  return (
    <Link
      href={href}
      className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-1.5 text-xs font-semibold text-[#3525cd] hover:bg-[#f8f6ff]"
    >
      {label}
    </Link>
  );
}

export function AdminSecurityCenterPage() {
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const runtimeConfig = useMemo(() => getFrontendRuntimeConfig(), []);
  const securityCapabilities = useMemo(() => getSecurityCapabilities(), []);
  const organizationCapabilities = useMemo(
    () => getOrganizationCapabilities(),
    [],
  );
  const teamCapabilities = useMemo(() => getTeamCapabilities(), []);

  const billingControlsHref =
    trimToNull(process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL) ??
    "/settings?tab=billing";
  const apiKeysHref = trimToNull(process.env.NEXT_PUBLIC_SETTINGS_API_KEYS_URL);
  const webhooksHref = trimToNull(
    process.env.NEXT_PUBLIC_SETTINGS_WEBHOOKS_URL,
  );
  const ssoHref =
    trimToNull(process.env.NEXT_PUBLIC_AUTH_SSO_URL) ??
    "/settings?tab=security";

  const auditRange = useMemo(() => resolveUsageDateRange("30d"), []);

  const loginPolicyQuery = useQuery({
    queryKey: ["security-center", "login-policy"],
    queryFn: getLoginPolicy,
    enabled: isAdminUser && securityCapabilities.loginPolicyEnabled,
    retry: false,
  });

  const postureQuery = useQuery({
    queryKey: ["security-center", "posture"],
    queryFn: getSecurityPosture,
    enabled: isAdminUser && securityCapabilities.postureEnabled,
    retry: false,
  });

  const sessionsQuery = useQuery({
    queryKey: ["security-center", "sessions"],
    queryFn: getSessions,
    enabled: isAdminUser && securityCapabilities.sessionsEnabled,
    retry: false,
  });

  const organizationSettingsQuery = useQuery({
    queryKey: ["security-center", "organization-settings"],
    queryFn: getOrganizationSettings,
    enabled: isAdminUser && organizationCapabilities.settingsEnabled,
    retry: false,
  });

  const organizationProfileQuery = useQuery({
    queryKey: ["security-center", "organization-profile"],
    queryFn: getOrganizationProfile,
    enabled: isAdminUser && organizationCapabilities.profileEnabled,
    retry: false,
  });

  const teamQuery = useQuery({
    queryKey: ["security-center", "team-members"],
    queryFn: () => listTeamMembers({ limit: 200, offset: 0 }),
    enabled: isAdminUser && teamCapabilities.listMembersEnabled,
    retry: false,
  });

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditLogs({
      from: auditRange.from,
      to: auditRange.to,
      limit: AUDIT_PAGE_LIMIT,
      offset: 0,
      organization_id: session?.organizationId ?? undefined,
      result: "all",
    }),
    queryFn: () =>
      listAuditLogs({
        from: auditRange.from,
        to: auditRange.to,
        limit: AUDIT_PAGE_LIMIT,
        offset: 0,
        organization_id: session?.organizationId ?? undefined,
        result: "all",
      }),
    enabled: isAdminUser,
    retry: false,
  });

  const forbiddenError =
    (loginPolicyQuery.isError &&
      isForbiddenError(loginPolicyQuery.error) &&
      loginPolicyQuery.error) ||
    (postureQuery.isError &&
      isForbiddenError(postureQuery.error) &&
      postureQuery.error) ||
    (sessionsQuery.isError &&
      isForbiddenError(sessionsQuery.error) &&
      sessionsQuery.error) ||
    (organizationSettingsQuery.isError &&
      isForbiddenError(organizationSettingsQuery.error) &&
      organizationSettingsQuery.error) ||
    (organizationProfileQuery.isError &&
      isForbiddenError(organizationProfileQuery.error) &&
      organizationProfileQuery.error) ||
    (teamQuery.isError &&
      isForbiddenError(teamQuery.error) &&
      teamQuery.error) ||
    (auditQuery.isError &&
      isForbiddenError(auditQuery.error) &&
      auditQuery.error) ||
    null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Security center restricted"
          description="Only owner and admin roles can access the organization security center."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Security center unavailable"
          description="Your current role no longer has access to this security surface."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  if (
    session?.organizationId == null &&
    !auditQuery.isLoading &&
    !organizationSettingsQuery.isLoading
  ) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title="Organization context missing"
          description="Open this page from an active organization workspace."
        />
      </section>
    );
  }

  const allowedDomains = new Set<string>();
  for (const domain of loginPolicyQuery.data?.domain_allowlist ?? []) {
    const normalized = domain.trim().toLowerCase();
    if (normalized) {
      allowedDomains.add(normalized);
    }
  }
  for (const domain of organizationSettingsQuery.data?.allowed_email_domains ??
    []) {
    const normalized = domain.trim().toLowerCase();
    if (normalized) {
      allowedDomains.add(normalized);
    }
  }
  const allowedDomainList = [...allowedDomains];

  const sessionExpiryMs = getJwtExpirationTimeMs(session?.accessToken ?? null);
  const teamMembers = teamQuery.data?.items ?? [];
  const roleSummary = summarizeRoles(teamMembers, session?.role ?? null);

  const auditItems = auditQuery.data?.items ?? [];
  const auditHealth = summarizeAuditHealth(auditItems);
  const warnings = buildWarnings({
    loginPolicy: loginPolicyQuery.data,
    posture: postureQuery.data,
    organizationSettings: organizationSettingsQuery.data,
    auditItems,
    missingAuditControls: auditHealth.missingControls,
    sessionsConfigured: securityCapabilities.sessionsEnabled,
    apiKeysUrl: apiKeysHref,
    webhooksUrl: webhooksHref,
  });
  const recommendations = buildRecommendations(warnings);

  const riskStatus: "ok" | "warning" | "unknown" =
    warnings.length === 0 ? "ok" : "warning";

  const controls: Array<{
    id: string;
    label: string;
    description: string;
    href: string | null;
  }> = [
    {
      id: "session-policy",
      label: "Session policy",
      description: "Timeout, MFA, SSO requirement, and invite-only controls.",
      href: "/settings?tab=security",
    },
    {
      id: "domain-restrictions",
      label: "Domain restrictions",
      description: "Allowed domains for login and membership.",
      href: "/settings?tab=organization",
    },
    {
      id: "role-settings",
      label: "Role settings",
      description: "Role assignment and team access controls.",
      href: "/settings?tab=organization",
    },
    {
      id: "retention",
      label: "Data retention",
      description: "Retention window and source download policy.",
      href: "/settings?tab=organization",
    },
    {
      id: "audit",
      label: "Audit logs",
      description: "Search and export organization audit evidence.",
      href: "/admin/audit-logs",
    },
    {
      id: "api-keys",
      label: "API keys",
      description: "Manage API keys and rotation policy when available.",
      href: apiKeysHref,
    },
    {
      id: "webhooks",
      label: "Webhooks",
      description:
        "Manage webhook endpoints and delivery posture when available.",
      href: webhooksHref,
    },
    {
      id: "sso",
      label: "SSO",
      description: "Open SSO setup and identity provider controls.",
      href: ssoHref,
    },
    {
      id: "billing",
      label: "Billing and plan controls",
      description: "Open plan and billing controls when configured.",
      href: billingControlsHref,
    },
  ];

  const retentionSummary = organizationSettingsQuery.data
    ? organizationSettingsQuery.data.retention_days == null
      ? "No retention limit configured"
      : `${organizationSettingsQuery.data.retention_days} day retention`
    : organizationCapabilities.settingsEnabled
      ? "Loading retention policy"
      : "Unavailable in this deployment";

  const sessionSummary = securityCapabilities.sessionsEnabled
    ? sessionsQuery.isLoading
      ? "Loading sessions"
      : sessionsQuery.isError
        ? "Session telemetry unavailable"
        : `${sessionsQuery.data?.length ?? 0} active sessions`
    : "Session endpoint unavailable";

  const auditSummary = auditQuery.isLoading
    ? "Loading audit health"
    : auditQuery.isError
      ? "Audit health unavailable"
      : `${auditQuery.data?.total ?? 0} events, ${auditHealth.failedCount} failures`;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          Rudix Admin
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          Organization security center
        </h1>
        <p className="max-w-4xl text-sm text-[#68647b]">
          Central security posture view for organization controls and
          operational risk. This page summarizes available signals and action
          links; it is not a compliance certification.
        </p>
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-[#2a2640]">
                Security overview
              </h2>
              <span
                className={`rounded-full px-2 py-1 text-[11px] font-semibold tracking-wide uppercase ${statusBadgeClass(riskStatus)}`}
              >
                {riskStatus === "ok"
                  ? "No active warnings"
                  : "Warnings present"}
              </span>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Auth and session status
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {runtimeConfig.authProviderRaw || "app"} · {state.status}
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  Session expiry: {formatSessionExpiry(sessionExpiryMs)}
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Roles summary
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {roleSummary}
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  {teamCapabilities.listMembersEnabled
                    ? "Derived from team membership."
                    : "Team listing endpoint is unavailable."}
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Allowed domains
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {allowedDomainList.length > 0
                    ? allowedDomainList.join(", ")
                    : "No restriction"}
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  Login and membership controls.
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Active sessions
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {sessionSummary}
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  {securityCapabilities.sessionsEnabled
                    ? "Session telemetry endpoint configured."
                    : "Placeholder shown until deployment support is enabled."}
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  API access status
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  Base API configured
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  Audit export:{" "}
                  {securityCapabilities.auditExportEnabled
                    ? "enabled"
                    : "unavailable"}
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Retention status
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {retentionSummary}
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  Source download policy:{" "}
                  {organizationSettingsQuery.data?.source_download ?? "unknown"}
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Audit health (30 days)
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {auditSummary}
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  High severity signals: {auditHealth.severeCount}
                </p>
              </article>

              <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
                <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Risky settings
                </p>
                <p className="mt-1 text-sm font-semibold text-[#2a2640]">
                  {warnings.length} unresolved warnings
                </p>
                <p className="mt-1 text-xs text-[#6a6780]">
                  Last posture audit:{" "}
                  {formatTimestamp(postureQuery.data?.last_audit_at)}
                </p>
              </article>
            </div>

            {auditQuery.isError &&
              isApiClientError(auditQuery.error) &&
              auditQuery.error.status === 429 && (
                <div className="mt-4">
                  <RateLimitState
                    compact
                    title="Audit health is rate-limited"
                    onRetry={() => {
                      void auditQuery.refetch();
                    }}
                  />
                </div>
              )}
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-[#3525cd]" aria-hidden />
              <h2 className="text-lg font-bold text-[#2a2640]">
                Security controls
              </h2>
            </div>
            <div className="space-y-3">
              {controls.map((control) => (
                <article
                  key={control.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-semibold text-[#2a2640]">
                      {control.label}
                    </p>
                    <p className="text-xs text-[#6a6780]">
                      {control.description}
                    </p>
                  </div>
                  <div>
                    {control.href ? (
                      <ActionLink href={control.href} label="Open control" />
                    ) : (
                      <span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                        Unavailable
                      </span>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-[#8a5f00]" aria-hidden />
              <h2 className="text-lg font-bold text-[#2a2640]">
                Unresolved warnings
              </h2>
            </div>

            {(loginPolicyQuery.isLoading ||
              organizationSettingsQuery.isLoading ||
              postureQuery.isLoading ||
              (teamCapabilities.listMembersEnabled && teamQuery.isLoading)) && (
              <LoadingState compact title="Loading security signals..." />
            )}

            {(loginPolicyQuery.isError ||
              organizationSettingsQuery.isError ||
              postureQuery.isError ||
              teamQuery.isError) &&
              !(
                isApiClientError(loginPolicyQuery.error) &&
                loginPolicyQuery.error.status === 429
              ) &&
              !(
                isApiClientError(organizationSettingsQuery.error) &&
                organizationSettingsQuery.error.status === 429
              ) &&
              !(
                isApiClientError(postureQuery.error) &&
                postureQuery.error.status === 429
              ) &&
              !(
                isApiClientError(teamQuery.error) &&
                teamQuery.error.status === 429
              ) && (
                <ErrorState
                  compact
                  error={
                    loginPolicyQuery.error ??
                    organizationSettingsQuery.error ??
                    postureQuery.error ??
                    teamQuery.error
                  }
                  description={getApiErrorMessage(
                    loginPolicyQuery.error ??
                      organizationSettingsQuery.error ??
                      postureQuery.error ??
                      teamQuery.error,
                  )}
                  onRetry={() => {
                    void loginPolicyQuery.refetch();
                    void organizationSettingsQuery.refetch();
                    void postureQuery.refetch();
                    void teamQuery.refetch();
                  }}
                />
              )}

            {(isApiClientError(loginPolicyQuery.error) &&
              loginPolicyQuery.error.status === 429) ||
            (isApiClientError(organizationSettingsQuery.error) &&
              organizationSettingsQuery.error.status === 429) ||
            (isApiClientError(postureQuery.error) &&
              postureQuery.error.status === 429) ||
            (isApiClientError(teamQuery.error) &&
              teamQuery.error.status === 429) ? (
              <RateLimitState
                compact
                title="Security signals are rate-limited"
                onRetry={() => {
                  void loginPolicyQuery.refetch();
                  void organizationSettingsQuery.refetch();
                  void postureQuery.refetch();
                  void teamQuery.refetch();
                }}
              />
            ) : null}

            {!loginPolicyQuery.isLoading &&
              !organizationSettingsQuery.isLoading &&
              !postureQuery.isLoading &&
              warnings.length === 0 && (
                <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                  No active warnings were detected from available controls.
                </p>
              )}

            {warnings.length > 0 && (
              <div className="space-y-3">
                {warnings.map((warning) => (
                  <article
                    key={warning.id}
                    className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3"
                  >
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <p className="text-sm font-semibold text-[#2a2640]">
                        {warning.title}
                      </p>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${severityBadgeClass(warning.severity)}`}
                      >
                        {warning.severity}
                      </span>
                    </div>
                    <p className="text-xs text-[#68647b]">
                      {warning.description}
                    </p>
                    {warning.href ? (
                      <div className="mt-2">
                        <ActionLink href={warning.href} label="Resolve" />
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-700" aria-hidden />
              <h2 className="text-lg font-bold text-[#2a2640]">
                Recommendations
              </h2>
            </div>
            <div className="space-y-3">
              {recommendations.map((item) => (
                <article
                  key={item.id}
                  className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3"
                >
                  <p className="text-sm font-semibold text-[#2a2640]">
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs text-[#68647b]">
                    {item.description}
                  </p>
                  <div className="mt-2">
                    <ActionLink href={item.href} label="Open" />
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-[#3525cd]" aria-hidden />
              <h2 className="text-lg font-bold text-[#2a2640]">
                Security links
              </h2>
            </div>
            <div className="grid gap-2">
              <ActionLink href="/admin/audit-logs" label="Audit logs" />
              <ActionLink
                href="/settings?tab=organization"
                label="Team settings"
              />
              <ActionLink
                href="/settings?tab=organization"
                label="Retention settings"
              />
              <ActionLink
                href={billingControlsHref}
                label="Billing and plan controls"
              />
              {apiKeysHref ? (
                <ActionLink href={apiKeysHref} label="API keys" />
              ) : null}
              {webhooksHref ? (
                <ActionLink href={webhooksHref} label="Webhooks" />
              ) : null}
            </div>
            <p className="mt-3 text-xs text-[#68647b]">
              Audit exports must remain sanitized and should never include
              secrets or raw private document content.
            </p>
          </section>
        </div>
      </div>

      {organizationProfileQuery.data?.plan ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm text-[#4f4a67]">
            <Link2 className="h-4 w-4 text-[#5d58a8]" aria-hidden />
            <span className="font-semibold text-[#2a2640]">Plan:</span>
            <span>{organizationProfileQuery.data.plan}</span>
          </div>
        </section>
      ) : null}
    </section>
  );
}
