import { z } from "zod";

import type { AppRole } from "@/lib/auth-session";
import type {
  IngestionDefaults,
  OrganizationProfile,
  OrganizationSettings,
} from "@/lib/api/organization";

// ── Zod schemas ───────────────────────────────────────────────────────────────

export const slugPattern = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$|^[a-z0-9]$/;
export const domainPattern =
  /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/;

export const orgProfileSchema = z.object({
  name: z.string().trim().min(1, "Organization name is required."),
  slug: z
    .string()
    .trim()
    .min(1, "Slug is required.")
    .regex(slugPattern, "Slug must be lowercase letters, digits, and hyphens."),
  primaryDomain: z
    .string()
    .trim()
    .refine(
      (v) => !v || domainPattern.test(v),
      "Enter a valid domain (e.g. example.com).",
    )
    .transform((v) => v ?? ""),
  domainAllowlist: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
  supportEmail: z
    .string()
    .trim()
    .refine(
      (v) => !v || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
      "Enter a valid support email address.",
    )
    .transform((v) => v ?? ""),
  description: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
});

export type OrgProfileFormValues = z.infer<typeof orgProfileSchema>;

export const workspaceDefaultsSchema = z.object({
  defaultMemberRole: z.enum(["member", "viewer"]),
  inviteOnly: z.boolean(),
  allowedEmailDomains: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
  defaultDocumentVisibility: z.enum(["public", "private"]),
  defaultCollection: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
  retentionDays: z.string().transform((v) => v ?? ""),
  sourceDownload: z.enum(["all", "admins", "none"]),
  evaluationAccess: z.boolean(),
  agenticAccess: z.boolean(),
  mcpAccess: z.boolean(),
  analyticsEnabled: z.boolean(),
});

export type WorkspaceDefaultsFormValues = z.infer<
  typeof workspaceDefaultsSchema
>;

export const ingestionDefaultsSchema = z.object({
  allowedFileTypes: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
  maxUploadSizeMb: z.string().transform((v) => v ?? ""),
  maxPageCount: z.string().transform((v) => v ?? ""),
  duplicateHandling: z.enum(["allow", "skip", "replace"]),
  autoIndex: z.boolean(),
  reindexPolicy: z.enum(["on_update", "manual"]),
  retryPolicy: z.enum(["never", "once", "three_times"]),
  defaultMetadataTags: z
    .string()
    .trim()
    .transform((v) => v ?? ""),
});

export type IngestionDefaultsFormValues = z.infer<
  typeof ingestionDefaultsSchema
>;

// ── Helper types ──────────────────────────────────────────────────────────────

export type SaveState = { tone: "success" | "error"; message: string } | null;

// ── Utility functions ─────────────────────────────────────────────────────────

export function isAdminLikeRole(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
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

export function toNullableNumber(s: string): number | null {
  const trimmed = s.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function formatDate(value: string | null): string {
  if (!value) return "Not available";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

export function profileToForm(p: OrganizationProfile): OrgProfileFormValues {
  return {
    name: p.name,
    slug: p.slug,
    primaryDomain: p.primary_domain ?? "",
    domainAllowlist: fromList(p.domain_allowlist),
    supportEmail: p.support_email ?? "",
    description: p.description ?? "",
  };
}

export function settingsToForm(
  s: OrganizationSettings,
): WorkspaceDefaultsFormValues {
  return {
    defaultMemberRole: s.default_member_role,
    inviteOnly: s.invite_only,
    allowedEmailDomains: fromList(s.allowed_email_domains),
    defaultDocumentVisibility: s.default_document_visibility,
    defaultCollection: s.default_collection ?? "",
    retentionDays: s.retention_days?.toString() ?? "",
    sourceDownload: s.source_download,
    evaluationAccess: s.evaluation_access,
    agenticAccess: s.agentic_access,
    mcpAccess: s.mcp_access,
    analyticsEnabled: s.analytics_enabled,
  };
}

export function ingestionToForm(
  d: IngestionDefaults,
): IngestionDefaultsFormValues {
  return {
    allowedFileTypes: fromList(d.allowed_file_types),
    maxUploadSizeMb: d.max_upload_size_mb?.toString() ?? "",
    maxPageCount: d.max_page_count?.toString() ?? "",
    duplicateHandling: d.duplicate_handling,
    autoIndex: d.auto_index,
    reindexPolicy: d.reindex_policy,
    retryPolicy: d.retry_policy,
    defaultMetadataTags: fromList(d.default_metadata_tags),
  };
}

// ── Shared sub-components ─────────────────────────────────────────────────────

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

export function ReadOnlyField({
  label,
  value,
  notAvailableLabel,
}: {
  label: string;
  value: string | null | undefined;
  notAvailableLabel: string;
}) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
        {label}
      </p>
      <div className="rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2 text-sm text-[#464555]">
        {value || notAvailableLabel}
      </div>
    </div>
  );
}

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
