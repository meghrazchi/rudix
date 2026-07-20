"use client";

import {
  AlertCircle,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  Code2,
  CreditCard,
  Database,
  Download,
  FileSearch2,
  Globe,
  Info,
  Key,
  Link2,
  LogIn,
  Settings2,
  ShieldCheck,
  Users,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

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
  matches: (action: string) => boolean;
}> = [
  {
    key: "auth-login-logout",
    matches: (action) =>
      action.startsWith("auth.login.") || action.startsWith("auth.logout."),
  },
  {
    key: "token-refresh-failure",
    matches: (action) => action === "auth.refresh.failed",
  },
  {
    key: "upload-delete",
    matches: (action) =>
      action.startsWith("document.upload.") ||
      action.startsWith("document.delete."),
  },
  {
    key: "policy-changes",
    matches: (action) => action.includes("policy"),
  },
  {
    key: "chat-export-share",
    matches: (action) =>
      action.startsWith("chat.") ||
      action.includes("export") ||
      action.includes("share"),
  },
  {
    key: "api-key-webhook",
    matches: (action) =>
      action.includes("api_key") || action.includes("webhook"),
  },
  {
    key: "admin-changes",
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

function formatTimestamp(
  value: string | null | undefined,
  unavailableLabel: string,
): string {
  if (!value) {
    return unavailableLabel;
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return value;
  }
  return new Date(parsed).toLocaleString();
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
  }).map((rule) => rule.key);

  return { failedCount, severeCount, missingControls };
}

function buildWarnings(
  params: {
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
  },
  t: ReturnType<typeof useTranslations>,
): SecurityWarning[] {
  const warnings: SecurityWarning[] = [];

  if (!params.sessionsConfigured) {
    warnings.push({
      id: "sessions-visibility-gap",
      title: "",
      description: "",
      severity: "medium",
      href: "/settings?tab=security",
    });
  }

  if (params.loginPolicy) {
    if (!params.loginPolicy.mfa_required) {
      warnings.push({
        id: "mfa-disabled",
        title: "",
        description: "",
        severity: "high",
        href: "/settings?tab=security",
      });
    }
    if (!params.loginPolicy.sso_required) {
      warnings.push({
        id: "sso-optional",
        title: "",
        description: "",
        severity: "medium",
        href: "/settings?tab=security",
      });
    }
    if (params.loginPolicy.domain_allowlist.length === 0) {
      warnings.push({
        id: "domain-allowlist-empty",
        title: "",
        description: "",
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
        title: "",
        description: "",
        severity: "medium",
        href: "/settings?tab=security",
      });
    }
  }

  if (params.organizationSettings) {
    if (params.organizationSettings.retention_days == null) {
      warnings.push({
        id: "retention-unbounded",
        title: "",
        description: "",
        severity: "high",
        href: "/settings?tab=organization",
      });
    }
    if (params.organizationSettings.source_download === "all") {
      warnings.push({
        id: "source-download-open",
        title: "",
        description: "",
        severity: "medium",
        href: "/settings?tab=organization",
      });
    }
  }

  if (params.posture) {
    if (params.posture.prompt_injection_protection === false) {
      warnings.push({
        id: "prompt-injection-disabled",
        title: "",
        description: "",
        severity: "high",
      });
    }
    if (params.posture.citation_validation === false) {
      warnings.push({
        id: "citation-validation-disabled",
        title: "",
        description: "",
        severity: "high",
      });
    }
    if (params.posture.tenant_isolation === false) {
      warnings.push({
        id: "tenant-isolation-inactive",
        title: "",
        description: "",
        severity: "high",
      });
    }
    if (params.posture.output_validation === false) {
      warnings.push({
        id: "output-validation-disabled",
        title: "",
        description: "",
        severity: "medium",
      });
    }
  }

  if (params.auditItems.length === 0) {
    warnings.push({
      id: "audit-events-empty",
      title: "",
      description: "",
      severity: "medium",
      href: "/admin/audit-logs",
    });
  }

  if (params.missingAuditControls.length > 0) {
    warnings.push({
      id: "audit-control-gaps",
      title: "",
      description: "",
      severity: "medium",
      href: "/admin/audit-logs",
    });
  }

  if (!params.apiKeysUrl) {
    warnings.push({
      id: "api-keys-control-missing",
      title: "",
      description: "",
      severity: "low",
    });
  }

  if (!params.webhooksUrl) {
    warnings.push({
      id: "webhooks-control-missing",
      title: "",
      description: "",
      severity: "low",
    });
  }

  const missingControls = params.missingAuditControls
    .map((key) => t(`auditRules.${key}`))
    .join(", ");

  return warnings.map((warning) => ({
    ...warning,
    title: t(`warnings.${warning.id}.title`),
    description:
      warning.id === "audit-control-gaps"
        ? t("warnings.audit-control-gaps.description", {
            controls: missingControls,
          })
        : t(`warnings.${warning.id}.description`),
  }));
}

function buildRecommendations(
  warnings: SecurityWarning[],
  t: ReturnType<typeof useTranslations>,
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
      title: t("recommendations.auditReview.title"),
      description: t("recommendations.auditReview.description"),
      href: "/admin/audit-logs",
    });
  }

  return [...recommendations.values()];
}

function ActionLink({
  href,
  label,
  variant = "outline",
}: {
  href: string;
  label: string;
  variant?: "primary" | "outline" | "link";
}) {
  const cls =
    variant === "primary"
      ? "inline-flex rounded-lg bg-[#2a2640] px-4 py-2 text-xs font-bold text-white hover:opacity-90"
      : variant === "link"
        ? "inline-flex px-2 py-1 text-sm font-bold text-[#3525cd] hover:underline"
        : "inline-flex rounded-lg border border-[#d2cee6] px-3 py-1.5 text-xs font-semibold text-[#3525cd] hover:bg-[#f8f6ff]";

  if (isExternalHref(href)) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={cls}>
        {label}
      </a>
    );
  }

  return (
    <Link href={href} className={cls}>
      {label}
    </Link>
  );
}

function getRecommendationStyle(
  severity: WarningSeverity,
  t: ReturnType<typeof useTranslations>,
): {
  borderClass: string;
  iconBgClass: string;
  badgeClass: string;
  badgeLabel: string;
  actionLabel: string;
  actionVariant: "primary" | "outline" | "link";
} {
  if (severity === "high") {
    return {
      borderClass: "border-l-rose-600",
      iconBgClass: "bg-rose-100 text-rose-800",
      badgeClass: "bg-rose-100 text-rose-800",
      badgeLabel: t("severity.high"),
      actionLabel: t("actions.fixNow"),
      actionVariant: "primary",
    };
  }
  if (severity === "medium") {
    return {
      borderClass: "border-l-amber-500",
      iconBgClass: "bg-amber-100 text-amber-800",
      badgeClass: "bg-amber-100 text-amber-800",
      badgeLabel: t("severity.medium"),
      actionLabel: t("actions.review"),
      actionVariant: "outline",
    };
  }
  return {
    borderClass: "border-l-[#3525cd]",
    iconBgClass: "bg-[#e2dfff] text-[#0f0069]",
    badgeClass: "bg-[#e2dfff] text-[#0f0069]",
    badgeLabel: t("severity.info"),
    actionLabel: t("actions.learnMore"),
    actionVariant: "link",
  };
}

function getWarningCategory(
  id: string,
  t: ReturnType<typeof useTranslations>,
): string {
  if (id.startsWith("audit")) return t("categories.infrastructure");
  if (
    id.includes("mfa") ||
    id.includes("sso") ||
    id.includes("session") ||
    id.includes("domain")
  )
    return t("categories.identity");
  if (id.includes("retention") || id.includes("source"))
    return t("categories.policy");
  if (
    id.includes("injection") ||
    id.includes("citation") ||
    id.includes("isolation") ||
    id.includes("validation")
  )
    return t("categories.aiSafety");
  if (id.includes("api") || id.includes("webhook"))
    return t("categories.integrations");
  return t("categories.security");
}

function getControlIcon(id: string) {
  switch (id) {
    case "session-policy":
      return Key;
    case "domain-restrictions":
      return Globe;
    case "role-settings":
      return Users;
    case "retention":
      return Database;
    case "audit":
      return FileSearch2;
    case "api-keys":
      return Code2;
    case "webhooks":
      return Webhook;
    case "sso":
      return LogIn;
    case "billing":
      return CreditCard;
    default:
      return ShieldCheck;
  }
}

export function AdminSecurityCenterPage() {
  const t = useTranslations("adminSecurityCenter");
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
          title={t("restricted")}
          description={t("restrictedDescription")}
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("unavailable")}
          description={t("unavailableDescription")}
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
          title={t("missingOrganization")}
          description={t("missingOrganizationDescription")}
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

  const teamMembers = teamQuery.data?.items ?? [];
  const auditItems = auditQuery.data?.items ?? [];
  const auditHealth = summarizeAuditHealth(auditItems);
  const warnings = buildWarnings(
    {
      loginPolicy: loginPolicyQuery.data,
      posture: postureQuery.data,
      organizationSettings: organizationSettingsQuery.data,
      auditItems,
      missingAuditControls: auditHealth.missingControls,
      sessionsConfigured: securityCapabilities.sessionsEnabled,
      apiKeysUrl: apiKeysHref,
      webhooksUrl: webhooksHref,
    },
    t,
  );
  const recommendations = buildRecommendations(warnings, t);

  const adminCount = teamMembers.filter((m) => m.role === "admin").length;
  const ownerCount = teamMembers.filter((m) => m.role === "owner").length;
  const elevatedCount = adminCount + ownerCount;
  const totalMembers = teamMembers.length;
  const elevatedRatio = totalMembers > 0 ? elevatedCount / totalMembers : 0;
  const isAuditHealthy =
    auditHealth.failedCount === 0 && auditHealth.severeCount === 0;

  const infoItems = recommendations
    .filter((r) => !warnings.some((w) => w.id === r.id))
    .map((r) => ({
      id: r.id,
      title: r.title,
      description: r.description,
      severity: "low" as WarningSeverity,
      href: r.href,
    }));
  const displayItems = [...warnings, ...infoItems];

  const controls: Array<{
    id: string;
    label: string;
    description: string;
    href: string | null;
  }> = [
    {
      id: "session-policy",
      label: t("controls.sessionPolicy.label"),
      description: t("controls.sessionPolicy.description"),
      href: "/settings?tab=security",
    },
    {
      id: "domain-restrictions",
      label: t("controls.domainRestrictions.label"),
      description: t("controls.domainRestrictions.description"),
      href: "/settings?tab=organization",
    },
    {
      id: "role-settings",
      label: t("controls.roleSettings.label"),
      description: t("controls.roleSettings.description"),
      href: "/settings?tab=organization",
    },
    {
      id: "retention",
      label: t("controls.dataRetention.label"),
      description: t("controls.dataRetention.description"),
      href: "/settings?tab=organization",
    },
    {
      id: "audit",
      label: t("controls.auditLogs.label"),
      description: t("controls.auditLogs.description"),
      href: "/admin/audit-logs",
    },
    {
      id: "api-keys",
      label: t("controls.apiKeys.label"),
      description: t("controls.apiKeys.description"),
      href: apiKeysHref,
    },
    {
      id: "webhooks",
      label: t("controls.webhooks.label"),
      description: t("controls.webhooks.description"),
      href: webhooksHref,
    },
    {
      id: "sso",
      label: t("controls.sso.label"),
      description: t("controls.sso.description"),
      href: ssoHref,
    },
    {
      id: "billing",
      label: t("controls.billing.label"),
      description: t("controls.billing.description"),
      href: billingControlsHref,
    },
  ];

  const retentionSummary = organizationSettingsQuery.data
    ? organizationSettingsQuery.data.retention_days == null
      ? t("summaries.noRetention")
      : t("summaries.retentionDays", {
          count: organizationSettingsQuery.data.retention_days,
        })
    : organizationCapabilities.settingsEnabled
      ? t("summaries.loadingRetention")
      : t("summaries.deploymentUnavailable");

  const sessionSummary = securityCapabilities.sessionsEnabled
    ? sessionsQuery.isLoading
      ? t("summaries.loadingSessions")
      : sessionsQuery.isError
        ? t("summaries.sessionTelemetryUnavailable")
        : t("summaries.activeSessions", {
            count: sessionsQuery.data?.length ?? 0,
          })
    : t("summaries.sessionEndpointUnavailable");

  const auditSummary = auditQuery.isLoading
    ? t("summaries.loadingAudit")
    : auditQuery.isError
      ? t("summaries.auditUnavailable")
      : t("summaries.auditEvents", {
          events: auditQuery.data?.total ?? 0,
          failures: auditHealth.failedCount,
        });

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      {/* Page Header */}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              {t("title")}
            </h1>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#3525cd]/20 bg-[#e2dfff]/40 px-3 py-1 text-xs font-semibold text-[#3525cd]">
              <ShieldCheck className="h-3 w-3" aria-hidden />
              {t("organizationAdmin")}
            </span>
          </div>
          <p className="max-w-2xl text-sm text-[#68647b]">{t("description")}</p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/admin/audit-logs"
            className="inline-flex items-center gap-2 rounded-lg border border-[#d7d4e8] bg-white px-4 py-2 text-sm font-medium text-[#2a2640] transition-colors hover:bg-[#f5f2ff]"
          >
            <Download className="h-4 w-4" aria-hidden />
            {t("exportLogs")}
          </Link>
        </div>
      </header>

      {/* Posture Summary Bento Grid */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-[#3525cd]" aria-hidden />
          <h2 className="text-lg font-bold text-[#2a2640]">
            {t("postureSummary")}
          </h2>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <article className="rounded-xl border border-[#e4e1f2] bg-white p-4 transition-colors hover:border-[#3525cd]">
            <p className="mb-2 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {t("authentication")}
            </p>
            <div className="flex items-center justify-between gap-1">
              <p className="truncate text-sm font-bold text-[#2a2640]">
                {runtimeConfig.authProviderRaw || t("configured")}
              </p>
              <span className="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-[9px] font-black tracking-wide text-emerald-800 uppercase">
                {t("active")}
              </span>
            </div>
            <p className="mt-2 text-[10px] text-[#6a6780]">{sessionSummary}</p>
          </article>

          <article className="rounded-xl border border-[#e4e1f2] bg-white p-4 transition-colors hover:border-[#3525cd]">
            <p className="mb-2 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {t("rolesAccess")}
            </p>
            <p className="text-sm font-bold text-[#2a2640]">
              {teamCapabilities.listMembersEnabled
                ? t("elevated", { count: elevatedCount })
                : t("unavailableShort")}
            </p>
            <p className="text-[10px] text-[#6a6780]">
              {teamCapabilities.listMembersEnabled
                ? t("adminOwner", { admins: adminCount, owners: ownerCount })
                : t("teamListingDisabled")}
            </p>
            {teamCapabilities.listMembersEnabled && totalMembers > 0 && (
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-[#f0ecf9]">
                <div
                  className="h-full rounded-full bg-[#3525cd]"
                  style={{ width: `${Math.min(elevatedRatio * 100, 100)}%` }}
                />
              </div>
            )}
          </article>

          <article className="rounded-xl border border-[#e4e1f2] bg-white p-4 transition-colors hover:border-[#3525cd]">
            <p className="mb-2 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {t("domainRestrictions")}
            </p>
            <div className="flex items-center gap-1.5">
              <Globe
                className="h-3.5 w-3.5 shrink-0 text-[#3525cd]"
                aria-hidden
              />
              <p className="text-sm font-bold text-[#2a2640]">
                {allowedDomainList.length > 0
                  ? t("domainCount", { count: allowedDomainList.length })
                  : t("open")}
              </p>
            </div>
            <p className="mt-2 text-[10px] text-[#6a6780]">
              {allowedDomainList.length > 0
                ? t("allowlistActive")
                : t("noRestriction")}
            </p>
          </article>

          <article className="rounded-xl border border-[#e4e1f2] bg-white p-4 transition-colors hover:border-[#3525cd]">
            <p className="mb-2 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {t("apiWebhooks")}
            </p>
            <p className="text-sm font-bold text-[#2a2640]">
              {apiKeysHref ? t("keysConfigured") : t("notConfigured")}
            </p>
            <div className="mt-2 flex gap-1">
              <span
                className={`h-2 w-2 rounded-full ${apiKeysHref ? "bg-emerald-500" : "bg-[#d7d4e8]"}`}
              />
              <span
                className={`h-2 w-2 rounded-full ${webhooksHref ? "bg-emerald-500" : "bg-[#d7d4e8]"}`}
              />
              <span
                className={`h-2 w-2 rounded-full ${securityCapabilities.auditExportEnabled ? "bg-emerald-500" : "bg-[#d7d4e8]"}`}
              />
            </div>
          </article>

          <article className="rounded-xl border border-[#e4e1f2] bg-white p-4 transition-colors hover:border-[#3525cd]">
            <p className="mb-2 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {t("dataRetention")}
            </p>
            <p className="text-sm font-bold text-[#2a2640]">
              {organizationSettingsQuery.data?.retention_days != null
                ? `${organizationSettingsQuery.data.retention_days}d`
                : t("defaultPolicy")}
            </p>
            <p className="mt-2 text-[10px] text-[#6a6780]">
              {retentionSummary}
            </p>
          </article>

          <article className="rounded-xl border border-[#e4e1f2] bg-white p-4 transition-colors hover:border-[#3525cd]">
            <p className="mb-2 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {t("auditHealth")}
            </p>
            <div className="flex items-center gap-1.5">
              {isAuditHealthy ? (
                <CheckCircle2
                  className="h-4 w-4 text-emerald-600"
                  aria-hidden
                />
              ) : (
                <AlertTriangle className="h-4 w-4 text-amber-500" aria-hidden />
              )}
              <p
                className={`text-sm font-bold ${isAuditHealthy ? "text-emerald-700" : "text-amber-700"}`}
              >
                {isAuditHealthy ? t("healthy") : t("warning")}
              </p>
            </div>
            <p className="mt-2 text-[10px] text-[#6a6780]">{auditSummary}</p>
          </article>
        </div>
      </section>

      {/* Main Layout: Recommendations + Controls */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        {/* Left: Security Recommendations */}
        <div>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-rose-600" aria-hidden />
              <h2 className="text-lg font-bold text-[#2a2640]">
                {t("securityRecommendations")}
              </h2>
            </div>
            <Link
              href="/admin/audit-logs"
              className="text-sm font-bold text-[#3525cd] hover:underline"
            >
              {t("viewAll")}
            </Link>
          </div>

          {(loginPolicyQuery.isLoading ||
            organizationSettingsQuery.isLoading ||
            postureQuery.isLoading ||
            (teamCapabilities.listMembersEnabled && teamQuery.isLoading)) && (
            <LoadingState compact title={t("loadingSecuritySignals")} />
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
              title={t("securityRateLimited")}
              onRetry={() => {
                void loginPolicyQuery.refetch();
                void organizationSettingsQuery.refetch();
                void postureQuery.refetch();
                void teamQuery.refetch();
              }}
            />
          ) : null}

          {auditQuery.isError &&
            isApiClientError(auditQuery.error) &&
            auditQuery.error.status === 429 && (
              <div className="mt-4">
                <RateLimitState
                  compact
                  title={t("auditRateLimited")}
                  onRetry={() => {
                    void auditQuery.refetch();
                  }}
                />
              </div>
            )}

          {!loginPolicyQuery.isLoading &&
            !organizationSettingsQuery.isLoading &&
            !postureQuery.isLoading &&
            warnings.length === 0 && (
              <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                {t("noWarnings")}
              </p>
            )}

          <div className="space-y-3">
            {displayItems.map((item) => {
              const style = getRecommendationStyle(item.severity, t);
              const category = getWarningCategory(item.id, t);
              return (
                <article
                  key={item.id}
                  className={`flex items-center gap-4 rounded-r-xl border border-l-4 border-[#e4e1f2] bg-white p-5 ${style.borderClass}`}
                >
                  <div
                    className={`shrink-0 rounded-lg p-2.5 ${style.iconBgClass}`}
                  >
                    {item.severity === "high" ? (
                      <AlertTriangle className="h-5 w-5" aria-hidden />
                    ) : item.severity === "medium" ? (
                      <AlertCircle className="h-5 w-5" aria-hidden />
                    ) : (
                      <Info className="h-5 w-5" aria-hidden />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded px-2 py-0.5 text-[9px] font-black tracking-wider uppercase ${style.badgeClass}`}
                      >
                        {style.badgeLabel}
                      </span>
                      <span className="text-[11px] text-[#6a6780]">
                        {category}
                      </span>
                    </div>
                    <h3 className="text-sm font-bold text-[#2a2640]">
                      {item.title}
                    </h3>
                    <p className="mt-1 text-xs text-[#68647b]">
                      {item.description}
                    </p>
                  </div>
                  {item.href ? (
                    <div className="shrink-0">
                      <ActionLink
                        href={item.href}
                        label={style.actionLabel}
                        variant={style.actionVariant}
                      />
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </div>

        {/* Right: Security Controls */}
        <div>
          <div className="mb-4 flex items-center gap-2">
            <Settings2 className="h-5 w-5 text-[#6a6780]" aria-hidden />
            <h2 className="text-lg font-bold text-[#2a2640]">
              {t("securityControls")}
            </h2>
          </div>
          <div className="space-y-3">
            {controls.map((control) => {
              const ControlIcon = getControlIcon(control.id);
              const sharedClass =
                "group flex items-center gap-3 rounded-xl border border-[#e4e1f2] bg-white p-4 transition-all hover:border-[#3525cd]";
              const inner = (
                <>
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#f5f2ff] text-[#6a6780] transition-colors group-hover:text-[#3525cd]">
                    <ControlIcon className="h-5 w-5" aria-hidden />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-[#2a2640]">
                      {control.label}
                    </p>
                    <p className="text-[11px] text-[#6a6780]">
                      {control.description}
                    </p>
                  </div>
                  {control.href ? (
                    <ChevronRight
                      className="ml-auto h-4 w-4 shrink-0 text-[#c7c4d8] transition-colors group-hover:text-[#3525cd]"
                      aria-hidden
                    />
                  ) : (
                    <span className="ml-auto shrink-0 rounded-lg bg-[#f0ecf9] px-2 py-1 text-[10px] font-semibold text-[#6a6780]">
                      {t("notApplicable")}
                    </span>
                  )}
                </>
              );
              if (!control.href) {
                return (
                  <article key={control.id} className={sharedClass}>
                    {inner}
                  </article>
                );
              }
              if (isExternalHref(control.href)) {
                return (
                  <a
                    key={control.id}
                    href={control.href}
                    target="_blank"
                    rel="noreferrer"
                    className={sharedClass}
                  >
                    {inner}
                  </a>
                );
              }
              return (
                <Link
                  key={control.id}
                  href={control.href}
                  className={sharedClass}
                >
                  {inner}
                </Link>
              );
            })}
          </div>
        </div>
      </div>

      {/* Footer Status Bar */}
      <footer className="flex flex-wrap items-center justify-between gap-4 border-t border-[#d7d4e8] pt-4 text-xs text-[#6a6780]">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
            {t("operational")}
          </div>
          <div>{t("compliance")}</div>
          {organizationProfileQuery.data?.plan && (
            <div className="flex items-center gap-1">
              <Link2 className="h-3.5 w-3.5 text-[#5d58a8]" aria-hidden />
              <span className="font-semibold text-[#2a2640]">{t("plan")}:</span>
              <span>{organizationProfileQuery.data.plan}</span>
            </div>
          )}
        </div>
        <div>
          {t("lastPostureAudit")}:{" "}
          <span className="font-mono text-xs text-[#3525cd]">
            {formatTimestamp(
              postureQuery.data?.last_audit_at,
              t("notAvailable"),
            )}
          </span>
        </div>
      </footer>
    </section>
  );
}
