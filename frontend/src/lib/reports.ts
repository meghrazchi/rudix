import type { AppRole } from "@/lib/auth-session";

export type ReportSectionId =
  | "overview"
  | "answer-quality"
  | "source-health"
  | "usage-adoption"
  | "permissions-access"
  | "feedback-issues"
  | "knowledge-gaps";

export type ReportSection = {
  id: ReportSectionId;
  label: string;
  description: string;
  href: string;
  allowedRoles: readonly AppRole[];
};

const PERSONAL_ROLES: readonly AppRole[] = [
  "member",
  "viewer",
  "reviewer",
  "admin",
  "owner",
];
const REVIEW_ROLES: readonly AppRole[] = ["reviewer", "admin", "owner"];
const ADMIN_ROLES: readonly AppRole[] = ["admin", "owner"];

export const REPORT_SECTIONS: readonly ReportSection[] = [
  {
    id: "overview",
    label: "Overview",
    description: "A personal snapshot of report activity and trends.",
    href: "/reports",
    allowedRoles: PERSONAL_ROLES,
  },
  {
    id: "answer-quality",
    label: "Answer Quality",
    description: "Confidence, grounding, and answer-quality trends.",
    href: "/reports/answer-quality",
    allowedRoles: REVIEW_ROLES,
  },
  {
    id: "source-health",
    label: "Source Health",
    description: "Freshness, indexing, and connector health.",
    href: "/reports/source-health",
    allowedRoles: REVIEW_ROLES,
  },
  {
    id: "usage-adoption",
    label: "Usage & Adoption",
    description: "Questions, active usage, and feature adoption.",
    href: "/reports/usage-adoption",
    allowedRoles: PERSONAL_ROLES,
  },
  {
    id: "permissions-access",
    label: "Permissions & Access",
    description: "Workspace access and permission posture.",
    href: "/reports/permissions-access",
    allowedRoles: ADMIN_ROLES,
  },
  {
    id: "feedback-issues",
    label: "Feedback & Issues",
    description: "Feedback themes and reported answer issues.",
    href: "/reports/feedback-issues",
    allowedRoles: PERSONAL_ROLES,
  },
  {
    id: "knowledge-gaps",
    label: "Knowledge Gaps",
    description: "Unanswered topics and missing source coverage.",
    href: "/reports/knowledge-gaps",
    allowedRoles: REVIEW_ROLES,
  },
];

export function getVisibleReportSections(role: AppRole): ReportSection[] {
  return REPORT_SECTIONS.filter((section) =>
    section.allowedRoles.includes(role),
  );
}

export function findReportSection(slug?: string): ReportSection | null {
  const id = slug || "overview";
  return REPORT_SECTIONS.find((section) => section.id === id) ?? null;
}

export function canViewReportSection(
  role: AppRole,
  section: ReportSection,
): boolean {
  return section.allowedRoles.includes(role);
}

export const REPORT_FILTER_KEYS = [
  "date",
  "workspace",
  "team",
  "user",
  "collection",
  "connector",
  "language",
  "model",
  "confidence",
] as const;

export type ReportFilterKey = (typeof REPORT_FILTER_KEYS)[number];
export type ReportFilters = Record<ReportFilterKey, string>;

export const DEFAULT_REPORT_FILTERS: ReportFilters = {
  date: "30d",
  workspace: "all",
  team: "all",
  user: "all",
  collection: "all",
  connector: "all",
  language: "all",
  model: "all",
  confidence: "all",
};

export function parseReportFilters(params: URLSearchParams): ReportFilters {
  return REPORT_FILTER_KEYS.reduce<ReportFilters>(
    (filters, key) => {
      filters[key] = params.get(key)?.trim() || DEFAULT_REPORT_FILTERS[key];
      return filters;
    },
    { ...DEFAULT_REPORT_FILTERS },
  );
}

export function serializeReportFilters(
  filters: ReportFilters,
): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of REPORT_FILTER_KEYS) {
    if (filters[key] !== DEFAULT_REPORT_FILTERS[key]) {
      params.set(key, filters[key]);
    }
  }
  return params;
}
