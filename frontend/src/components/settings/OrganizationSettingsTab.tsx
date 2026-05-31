"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle,
  Building2,
  Copy,
  CopyCheck,
  FileStack,
  Lock,
  Settings2,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { TeamManagementSection } from "@/components/settings/TeamManagementSection";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getIngestionDefaults,
  getOrganizationCapabilities,
  getOrganizationProfile,
  getOrganizationSettings,
  transferOwnership,
  archiveOrganization,
  exportOrganizationData,
  deleteOrganization,
  updateIngestionDefaults,
  updateOrganizationProfile,
  updateOrganizationSettings,
  type IngestionDefaults,
  type OrganizationProfile,
  type OrganizationSettings,
} from "@/lib/api/organization";
import type { AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";
import { orgAvatarColor, orgInitials } from "@/lib/workspace";

// ── Zod schemas ───────────────────────────────────────────────────────────────

const slugPattern = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$|^[a-z0-9]$/;
const domainPattern =
  /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/;

const orgProfileSchema = z.object({
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
  domainAllowlist: z.string().trim().transform((v) => v ?? ""),
  supportEmail: z
    .string()
    .trim()
    .refine(
      (v) => !v || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
      "Enter a valid support email address.",
    )
    .transform((v) => v ?? ""),
  description: z.string().trim().transform((v) => v ?? ""),
});

type OrgProfileFormValues = z.infer<typeof orgProfileSchema>;

const workspaceDefaultsSchema = z.object({
  defaultMemberRole: z.enum(["member", "viewer"]),
  inviteOnly: z.boolean(),
  allowedEmailDomains: z.string().trim().transform((v) => v ?? ""),
  defaultDocumentVisibility: z.enum(["public", "private"]),
  defaultCollection: z.string().trim().transform((v) => v ?? ""),
  retentionDays: z.string().transform((v) => v ?? ""),
  sourceDownload: z.enum(["all", "admins", "none"]),
  evaluationAccess: z.boolean(),
  agenticAccess: z.boolean(),
  mcpAccess: z.boolean(),
});

type WorkspaceDefaultsFormValues = z.infer<typeof workspaceDefaultsSchema>;

const ingestionDefaultsSchema = z.object({
  allowedFileTypes: z.string().trim().transform((v) => v ?? ""),
  maxUploadSizeMb: z.string().transform((v) => v ?? ""),
  maxPageCount: z.string().transform((v) => v ?? ""),
  duplicateHandling: z.enum(["allow", "skip", "replace"]),
  autoIndex: z.boolean(),
  reindexPolicy: z.enum(["on_update", "manual"]),
  retryPolicy: z.enum(["never", "once", "three_times"]),
  defaultMetadataTags: z.string().trim().transform((v) => v ?? ""),
});

type IngestionDefaultsFormValues = z.infer<typeof ingestionDefaultsSchema>;

// ── Helper types ──────────────────────────────────────────────────────────────

type SaveState = { tone: "success" | "error"; message: string } | null;

// ── Utility functions ─────────────────────────────────────────────────────────

function isAdminLikeRole(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
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

function toNullableNumber(s: string): number | null {
  const trimmed = s.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function formatDate(value: string | null): string {
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

function profileToForm(p: OrganizationProfile): OrgProfileFormValues {
  return {
    name: p.name,
    slug: p.slug,
    primaryDomain: p.primary_domain ?? "",
    domainAllowlist: fromList(p.domain_allowlist),
    supportEmail: p.support_email ?? "",
    description: p.description ?? "",
  };
}

function settingsToForm(s: OrganizationSettings): WorkspaceDefaultsFormValues {
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
  };
}

function ingestionToForm(d: IngestionDefaults): IngestionDefaultsFormValues {
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

function FieldLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-[10px] font-semibold uppercase tracking-widest text-[#464555]"
    >
      {children}
    </label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-[#464555]">
        {label}
      </p>
      <div className="rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2 text-sm text-[#464555]">
        {value || "Not available"}
      </div>
    </div>
  );
}

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
        {description && (
          <p className="text-xs text-[#464555]">{description}</p>
        )}
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

// ── Main component ────────────────────────────────────────────────────────────

export function OrganizationSettingsTab() {
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role ?? null;
  const isAdmin = isAdminLikeRole(role);
  const isOwner = role === "owner";

  const capabilities = useMemo(() => getOrganizationCapabilities(), []);

  const billingHref =
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL?.trim() || "/admin";

  // ── Org ID copy ─────────────────────────────────────────────────────────────
  const [orgIdCopied, setOrgIdCopied] = useState(false);

  function handleCopyOrgId(): void {
    const orgId = session?.organizationId;
    if (!orgId) return;
    void navigator.clipboard.writeText(orgId).then(() => {
      setOrgIdCopied(true);
      setTimeout(() => setOrgIdCopied(false), 2000);
    });
  }

  // ── Organization profile form ───────────────────────────────────────────────
  const [profileSaveState, setProfileSaveState] = useState<SaveState>(null);
  const profileLastSavedRef = useRef<OrgProfileFormValues | null>(null);

  const defaultProfileValues: OrgProfileFormValues = {
    name: session?.organizationName ?? "",
    slug: "",
    primaryDomain: "",
    domainAllowlist: "",
    supportEmail: "",
    description: "",
  };

  const profileForm = useForm<OrgProfileFormValues>({
    resolver: zodResolver(orgProfileSchema),
    defaultValues: defaultProfileValues,
    mode: "onSubmit",
  });

  const watchedOrgName = useWatch({
    control: profileForm.control,
    name: "name",
    defaultValue: defaultProfileValues.name,
  });

  const profileQuery = useQuery({
    queryKey: ["organization", "profile"],
    queryFn: getOrganizationProfile,
    enabled: capabilities.profileEnabled,
    retry: false,
  });

  useEffect(() => {
    if (!profileQuery.data) return;
    const values = profileToForm(profileQuery.data);
    profileLastSavedRef.current = values;
    profileForm.reset(values);
  }, [profileForm, profileQuery.data]);

  const profileSaveMutation = useMutation({
    mutationFn: (values: OrgProfileFormValues) =>
      updateOrganizationProfile({
        name: values.name,
        slug: values.slug,
        primary_domain: values.primaryDomain || null,
        domain_allowlist: toList(values.domainAllowlist),
        support_email: values.supportEmail || null,
        description: values.description || null,
      }),
    onSuccess: (updated) => {
      const values = profileToForm(updated);
      profileLastSavedRef.current = values;
      profileForm.reset(values);
      setProfileSaveState({
        tone: "success",
        message: "Organization profile saved.",
      });
    },
    onError: (error) => {
      setProfileSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveProfile(): Promise<void> {
    setProfileSaveState(null);
    const valid = await profileForm.trigger();
    if (!valid) return;
    await profileSaveMutation.mutateAsync(profileForm.getValues());
  }

  function handleDiscardProfile(): void {
    const last = profileLastSavedRef.current ?? defaultProfileValues;
    profileForm.reset(last);
    setProfileSaveState(null);
  }

  // ── Workspace defaults form ─────────────────────────────────────────────────
  const [workspaceSaveState, setWorkspaceSaveState] = useState<SaveState>(null);
  const workspaceLastSavedRef = useRef<WorkspaceDefaultsFormValues | null>(null);

  const defaultWorkspaceValues: WorkspaceDefaultsFormValues = {
    defaultMemberRole: "member",
    inviteOnly: false,
    allowedEmailDomains: "",
    defaultDocumentVisibility: "private",
    defaultCollection: "",
    retentionDays: "",
    sourceDownload: "admins",
    evaluationAccess: false,
    agenticAccess: false,
    mcpAccess: false,
  };

  const workspaceForm = useForm<WorkspaceDefaultsFormValues>({
    resolver: zodResolver(workspaceDefaultsSchema),
    defaultValues: defaultWorkspaceValues,
    mode: "onSubmit",
  });

  const settingsQuery = useQuery({
    queryKey: ["organization", "settings"],
    queryFn: getOrganizationSettings,
    enabled: capabilities.settingsEnabled && isAdmin,
    retry: false,
  });

  useEffect(() => {
    if (!settingsQuery.data) return;
    const values = settingsToForm(settingsQuery.data);
    workspaceLastSavedRef.current = values;
    workspaceForm.reset(values);
  }, [workspaceForm, settingsQuery.data]);

  const workspaceSaveMutation = useMutation({
    mutationFn: (values: WorkspaceDefaultsFormValues) =>
      updateOrganizationSettings({
        default_member_role: values.defaultMemberRole,
        invite_only: values.inviteOnly,
        allowed_email_domains: toList(values.allowedEmailDomains),
        default_document_visibility: values.defaultDocumentVisibility,
        default_collection: values.defaultCollection || null,
        retention_days: toNullableNumber(values.retentionDays),
        source_download: values.sourceDownload,
        evaluation_access: values.evaluationAccess,
        agentic_access: values.agenticAccess,
        mcp_access: values.mcpAccess,
      }),
    onSuccess: (updated) => {
      const values = settingsToForm(updated);
      workspaceLastSavedRef.current = values;
      workspaceForm.reset(values);
      setWorkspaceSaveState({
        tone: "success",
        message: "Workspace defaults saved.",
      });
    },
    onError: (error) => {
      setWorkspaceSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveWorkspace(): Promise<void> {
    setWorkspaceSaveState(null);
    const valid = await workspaceForm.trigger();
    if (!valid) return;
    await workspaceSaveMutation.mutateAsync(workspaceForm.getValues());
  }

  function handleDiscardWorkspace(): void {
    const last = workspaceLastSavedRef.current ?? defaultWorkspaceValues;
    workspaceForm.reset(last);
    setWorkspaceSaveState(null);
  }

  // ── Ingestion defaults form ─────────────────────────────────────────────────
  const [ingestionSaveState, setIngestionSaveState] = useState<SaveState>(null);
  const ingestionLastSavedRef = useRef<IngestionDefaultsFormValues | null>(null);

  const defaultIngestionValues: IngestionDefaultsFormValues = {
    allowedFileTypes: "",
    maxUploadSizeMb: "",
    maxPageCount: "",
    duplicateHandling: "skip",
    autoIndex: true,
    reindexPolicy: "on_update",
    retryPolicy: "once",
    defaultMetadataTags: "",
  };

  const ingestionForm = useForm<IngestionDefaultsFormValues>({
    resolver: zodResolver(ingestionDefaultsSchema),
    defaultValues: defaultIngestionValues,
    mode: "onSubmit",
  });

  const ingestionQuery = useQuery({
    queryKey: ["organization", "ingestion"],
    queryFn: getIngestionDefaults,
    enabled: capabilities.ingestionEnabled && isAdmin,
    retry: false,
  });

  useEffect(() => {
    if (!ingestionQuery.data) return;
    const values = ingestionToForm(ingestionQuery.data);
    ingestionLastSavedRef.current = values;
    ingestionForm.reset(values);
  }, [ingestionForm, ingestionQuery.data]);

  const ingestionSaveMutation = useMutation({
    mutationFn: (values: IngestionDefaultsFormValues) =>
      updateIngestionDefaults({
        allowed_file_types: toList(values.allowedFileTypes),
        max_upload_size_mb: toNullableNumber(values.maxUploadSizeMb),
        max_page_count: toNullableNumber(values.maxPageCount),
        duplicate_handling: values.duplicateHandling,
        auto_index: values.autoIndex,
        reindex_policy: values.reindexPolicy,
        retry_policy: values.retryPolicy,
        default_metadata_tags: toList(values.defaultMetadataTags),
      }),
    onSuccess: (updated) => {
      const values = ingestionToForm(updated);
      ingestionLastSavedRef.current = values;
      ingestionForm.reset(values);
      setIngestionSaveState({
        tone: "success",
        message: "Ingestion defaults saved.",
      });
    },
    onError: (error) => {
      setIngestionSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveIngestion(): Promise<void> {
    setIngestionSaveState(null);
    const valid = await ingestionForm.trigger();
    if (!valid) return;
    await ingestionSaveMutation.mutateAsync(ingestionForm.getValues());
  }

  function handleDiscardIngestion(): void {
    const last = ingestionLastSavedRef.current ?? defaultIngestionValues;
    ingestionForm.reset(last);
    setIngestionSaveState(null);
  }

  // ── Danger zone ─────────────────────────────────────────────────────────────
  const [dangerState, setDangerState] = useState<SaveState>(null);
  const [transferTarget, setTransferTarget] = useState("");

  const transferMutation = useMutation({
    mutationFn: (toUserId: string) => transferOwnership(toUserId),
    onSuccess: () => {
      setTransferTarget("");
      setDangerState({
        tone: "success",
        message: "Ownership transfer initiated.",
      });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: archiveOrganization,
    onSuccess: () => {
      setDangerState({
        tone: "success",
        message: "Workspace archived successfully.",
      });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportOrganizationData,
    onSuccess: (result) => {
      const msg = result.download_url
        ? `Export ready. Download URL: ${result.download_url}`
        : "Export request submitted. You will be notified when it is ready.";
      setDangerState({ tone: "success", message: msg });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteOrganization,
    onSuccess: () => {
      setDangerState({
        tone: "success",
        message:
          "Organization deletion initiated. All documents, chunks, vectors, chats, evaluations, and audit logs will be permanently removed.",
      });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const isDangerBusy =
    transferMutation.isPending ||
    archiveMutation.isPending ||
    exportMutation.isPending ||
    deleteMutation.isPending;

  // ── Watched form values ─────────────────────────────────────────────────────
  const watchedInviteOnly = workspaceForm.watch("inviteOnly");
  const watchedEvalAccess = workspaceForm.watch("evaluationAccess");
  const watchedAgenticAccess = workspaceForm.watch("agenticAccess");
  const watchedMcpAccess = workspaceForm.watch("mcpAccess");
  const watchedAutoIndex = ingestionForm.watch("autoIndex");

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* ── 1. Organization Identity ── */}
      <section
        className="bg-white border border-[#c7c4d8] rounded-2xl p-6"
        aria-label="Organization section"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Building2 size={20} className="text-[#3525cd]" aria-hidden="true" />
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Organization Profile
            </h2>
          </div>
          {!capabilities.profileEnabled && <DeploymentControlledBadge />}
        </div>

        {/* Always-visible: org ID + basic session info */}
        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-[#464555]">
              Organization ID
            </p>
            {session?.organizationId ? (
              <div className="flex items-center justify-between gap-2 rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2">
                <span className="max-w-[180px] truncate font-mono text-xs text-[#464555]">
                  {session.organizationId}
                </span>
                <button
                  type="button"
                  onClick={handleCopyOrgId}
                  aria-label="Copy organization ID"
                  className="shrink-0 rounded-lg border border-[#c7c4d8] px-2 py-0.5 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff] transition-colors"
                >
                  {orgIdCopied ? (
                    <CopyCheck size={12} aria-hidden="true" />
                  ) : (
                    <Copy size={12} aria-hidden="true" />
                  )}
                  <span className="sr-only">
                    {orgIdCopied ? "Copied!" : "Copy"}
                  </span>
                </button>
              </div>
            ) : (
              <div className="rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2 text-sm text-[#464555]">
                Not assigned
              </div>
            )}
          </div>

          <ReadOnlyField
            label="Organization Name"
            value={session?.organizationName ?? "Not assigned"}
          />
        </div>

        {/* Profile API content */}
        {!capabilities.profileEnabled ? (
          <p className="text-sm text-[#777587]">
            Extended profile settings (slug, domains, support email) are not
            available — deployment-controlled.
          </p>
        ) : profileQuery.isLoading ? (
          <LoadingState compact title="Loading organization profile..." />
        ) : profileQuery.isError ? (
          <ErrorState
            compact
            error={profileQuery.error}
            description={getApiErrorMessage(profileQuery.error)}
            onRetry={() => {
              void profileQuery.refetch();
            }}
          />
        ) : isAdmin ? (
          /* Editable profile form for owner/admin */
          <div className="space-y-4">
            {/* Avatar preview */}
            <div className="flex items-center gap-4 rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
              {(() => {
                const colors = orgAvatarColor(watchedOrgName);
                const initials = orgInitials(watchedOrgName || "W");
                return (
                  <span
                    className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-base font-bold"
                    style={{ backgroundColor: colors.bg, color: colors.text }}
                    aria-hidden
                  >
                    {initials}
                  </span>
                );
              })()}
              <div>
                <p className="text-sm font-semibold text-[#2a2640]">
                  {watchedOrgName.trim() || "Workspace name"}
                </p>
                <p className="text-xs text-[#7a7693]">
                  Initials and color are derived from the workspace name and shown throughout the app.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <FieldLabel htmlFor="org-name">Name</FieldLabel>
                <input
                  id="org-name"
                  {...profileForm.register("name")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
                {profileForm.formState.errors.name?.message && (
                  <p role="alert" className="text-xs text-rose-700">
                    {profileForm.formState.errors.name.message}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="org-slug">Slug</FieldLabel>
                <input
                  id="org-slug"
                  {...profileForm.register("slug")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] font-mono outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                  placeholder="my-org"
                />
                {profileForm.formState.errors.slug?.message && (
                  <p role="alert" className="text-xs text-rose-700">
                    {profileForm.formState.errors.slug.message}
                  </p>
                )}
                <p className="text-xs text-[#777587]">
                  Lowercase letters, digits, and hyphens only.
                </p>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="org-primary-domain">
                  Primary Domain
                </FieldLabel>
                <input
                  id="org-primary-domain"
                  {...profileForm.register("primaryDomain")}
                  placeholder="example.com"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
                {profileForm.formState.errors.primaryDomain?.message && (
                  <p role="alert" className="text-xs text-rose-700">
                    {profileForm.formState.errors.primaryDomain.message}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="org-support-email">
                  Support Email
                </FieldLabel>
                <input
                  id="org-support-email"
                  type="email"
                  {...profileForm.register("supportEmail")}
                  placeholder="support@example.com"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
                {profileForm.formState.errors.supportEmail?.message && (
                  <p role="alert" className="text-xs text-rose-700">
                    {profileForm.formState.errors.supportEmail.message}
                  </p>
                )}
              </div>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="org-domain-allowlist">
                Domain Allowlist
              </FieldLabel>
              <input
                id="org-domain-allowlist"
                {...profileForm.register("domainAllowlist")}
                placeholder="example.com, partner.org"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
              />
              <p className="text-xs text-[#777587]">
                Comma-separated list of domains (e.g. <code className="rounded bg-[#f0eeff] px-1 font-mono text-[#3525cd]">acme.com, partner.org</code>). Users with matching email addresses can join this workspace without an invitation.
              </p>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="org-description">Description</FieldLabel>
              <textarea
                id="org-description"
                {...profileForm.register("description")}
                rows={3}
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all resize-none"
              />
            </div>

            {/* Profile API metadata */}
            {profileQuery.data && (
              <div className="grid grid-cols-1 gap-3 rounded-xl border border-[#e4e1ee] bg-[#f5f2ff]/50 p-4 sm:grid-cols-2">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-[#464555]">
                    Created
                  </p>
                  <p className="mt-0.5 text-sm text-[#2f2a46]">
                    {formatDate(profileQuery.data.created_at)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-[#464555]">
                    Current Plan
                  </p>
                  <p className="mt-0.5 text-sm text-[#2f2a46]">
                    {profileQuery.data.plan ?? "Not available"}{" "}
                    <Link
                      href={billingHref}
                      className="text-[#3525cd] underline-offset-2 hover:underline text-xs"
                    >
                      View billing
                    </Link>
                  </p>
                </div>
              </div>
            )}

            <div className="flex items-center justify-end gap-3">
              <SaveFeedback state={profileSaveState} />
              <button
                type="button"
                onClick={handleDiscardProfile}
                disabled={profileSaveMutation.isPending}
                className="rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleSaveProfile();
                }}
                disabled={profileSaveMutation.isPending}
                aria-label="Save organization profile"
                className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
              >
                {profileSaveMutation.isPending ? "Saving…" : "Save profile"}
              </button>
            </div>
          </div>
        ) : (
          /* Read-only profile for member/viewer */
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <ReadOnlyField label="Slug" value={profileQuery.data?.slug} />
            <ReadOnlyField
              label="Primary Domain"
              value={profileQuery.data?.primary_domain}
            />
            <ReadOnlyField
              label="Support Email"
              value={profileQuery.data?.support_email}
            />
            <ReadOnlyField
              label="Description"
              value={profileQuery.data?.description}
            />
            <ReadOnlyField
              label="Created"
              value={formatDate(profileQuery.data?.created_at ?? null)}
            />
            <ReadOnlyField
              label="Current Plan"
              value={profileQuery.data?.plan}
            />
          </div>
        )}
      </section>

      {/* ── 2. Workspace Defaults ── */}
      <section
        className="bg-white border border-[#c7c4d8] rounded-2xl p-6"
        aria-label="Workspace defaults section"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Settings2
              size={20}
              className="text-[#3525cd]"
              aria-hidden="true"
            />
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Workspace Defaults
            </h2>
          </div>
          {!capabilities.settingsEnabled && <DeploymentControlledBadge />}
        </div>

        {!capabilities.settingsEnabled ? (
          <p className="text-sm text-[#777587]">
            Workspace defaults are not available — deployment-controlled.
          </p>
        ) : !isAdmin ? (
          <ForbiddenState
            compact
            title="Workspace defaults restricted"
            description="Workspace defaults can only be viewed and edited by owner/admin roles."
            backHref="/dashboard"
            backLabel="Back to dashboard"
          />
        ) : settingsQuery.isLoading ? (
          <LoadingState compact title="Loading workspace defaults..." />
        ) : settingsQuery.isError ? (
          <ErrorState
            compact
            error={settingsQuery.error}
            description={getApiErrorMessage(settingsQuery.error)}
            onRetry={() => {
              void settingsQuery.refetch();
            }}
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <FieldLabel htmlFor="ws-default-role">
                  Default Member Role
                </FieldLabel>
                <select
                  id="ws-default-role"
                  {...workspaceForm.register("defaultMemberRole")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="member">member</option>
                  <option value="viewer">viewer</option>
                </select>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ws-visibility">
                  Default Document Visibility
                </FieldLabel>
                <select
                  id="ws-visibility"
                  {...workspaceForm.register("defaultDocumentVisibility")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="private">private</option>
                  <option value="public">public</option>
                </select>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ws-source-download">
                  Source Download
                </FieldLabel>
                <select
                  id="ws-source-download"
                  {...workspaceForm.register("sourceDownload")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="all">all members</option>
                  <option value="admins">admins only</option>
                  <option value="none">disabled</option>
                </select>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ws-retention">
                  Retention Policy (days)
                </FieldLabel>
                <select
                  id="ws-retention"
                  {...workspaceForm.register("retentionDays")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="">No retention limit</option>
                  <option value="30">30 days</option>
                  <option value="60">60 days</option>
                  <option value="90">90 days</option>
                  <option value="180">180 days</option>
                  <option value="365">365 days</option>
                </select>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ws-allowed-domains">
                  Allowed Email Domains
                </FieldLabel>
                <input
                  id="ws-allowed-domains"
                  {...workspaceForm.register("allowedEmailDomains")}
                  placeholder="example.com, partner.org"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ws-collection">
                  Default Collection
                </FieldLabel>
                <input
                  id="ws-collection"
                  {...workspaceForm.register("defaultCollection")}
                  placeholder="general"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
              </div>
            </div>

            {/* Toggles */}
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                <div>
                  <label
                    htmlFor="ws-invite-only"
                    className="text-sm font-semibold text-[#1b1b24]"
                  >
                    Invite-only mode
                  </label>
                  <p className="text-xs text-[#464555]">
                    Restrict new members to invited users only
                  </p>
                </div>
                <ToggleSwitch
                  id="ws-invite-only"
                  checked={watchedInviteOnly}
                  onChange={(v) =>
                    workspaceForm.setValue("inviteOnly", v, {
                      shouldDirty: true,
                    })
                  }
                />
              </div>

              <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                <div>
                  <label
                    htmlFor="ws-eval-access"
                    className="text-sm font-semibold text-[#1b1b24]"
                  >
                    Evaluation access
                  </label>
                  <p className="text-xs text-[#464555]">
                    Allow members to run RAG pipeline evaluations
                  </p>
                </div>
                <ToggleSwitch
                  id="ws-eval-access"
                  checked={watchedEvalAccess}
                  onChange={(v) =>
                    workspaceForm.setValue("evaluationAccess", v, {
                      shouldDirty: true,
                    })
                  }
                />
              </div>

              <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                <div>
                  <label
                    htmlFor="ws-agentic-access"
                    className="text-sm font-semibold text-[#1b1b24]"
                  >
                    Agentic access
                  </label>
                  <p className="text-xs text-[#464555]">
                    Allow members to use agentic query modes
                  </p>
                </div>
                <ToggleSwitch
                  id="ws-agentic-access"
                  checked={watchedAgenticAccess}
                  onChange={(v) =>
                    workspaceForm.setValue("agenticAccess", v, {
                      shouldDirty: true,
                    })
                  }
                />
              </div>

              <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                <div>
                  <label
                    htmlFor="ws-mcp-access"
                    className="text-sm font-semibold text-[#1b1b24]"
                  >
                    MCP access
                  </label>
                  <p className="text-xs text-[#464555]">
                    Allow members to use MCP integrations when enabled
                  </p>
                </div>
                <ToggleSwitch
                  id="ws-mcp-access"
                  checked={watchedMcpAccess}
                  onChange={(v) =>
                    workspaceForm.setValue("mcpAccess", v, {
                      shouldDirty: true,
                    })
                  }
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3">
              <SaveFeedback state={workspaceSaveState} />
              <button
                type="button"
                onClick={handleDiscardWorkspace}
                disabled={workspaceSaveMutation.isPending}
                className="rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleSaveWorkspace();
                }}
                disabled={workspaceSaveMutation.isPending}
                aria-label="Save workspace defaults"
                className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
              >
                {workspaceSaveMutation.isPending
                  ? "Saving…"
                  : "Save workspace defaults"}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── 3. Team Management ── */}
      <TeamManagementSection role={role} />

      {/* ── 4. Document & Ingestion Defaults ── */}
      <section
        className="bg-white border border-[#c7c4d8] rounded-2xl p-6"
        aria-label="Document and ingestion defaults section"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <FileStack
              size={20}
              className="text-[#3525cd]"
              aria-hidden="true"
            />
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Document &amp; Ingestion Defaults
            </h2>
          </div>
          {!capabilities.ingestionEnabled && <DeploymentControlledBadge />}
        </div>

        {!capabilities.ingestionEnabled ? (
          <p className="text-sm text-[#777587]">
            Ingestion defaults are not available — deployment-controlled.
          </p>
        ) : !isAdmin ? (
          <ForbiddenState
            compact
            title="Ingestion defaults restricted"
            description="Ingestion defaults can only be edited by owner/admin roles."
            backHref="/dashboard"
            backLabel="Back to dashboard"
          />
        ) : ingestionQuery.isLoading ? (
          <LoadingState compact title="Loading ingestion defaults..." />
        ) : ingestionQuery.isError ? (
          <ErrorState
            compact
            error={ingestionQuery.error}
            description={getApiErrorMessage(ingestionQuery.error)}
            onRetry={() => {
              void ingestionQuery.refetch();
            }}
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <FieldLabel htmlFor="ing-file-types">
                  Allowed File Types
                </FieldLabel>
                <input
                  id="ing-file-types"
                  {...ingestionForm.register("allowedFileTypes")}
                  placeholder="pdf, docx, txt"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
                <p className="text-xs text-[#777587]">Comma-separated.</p>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ing-max-size">
                  Max Upload Size (MB)
                </FieldLabel>
                <input
                  id="ing-max-size"
                  type="number"
                  min={1}
                  {...ingestionForm.register("maxUploadSizeMb")}
                  placeholder="50"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ing-max-pages">Max Page Count</FieldLabel>
                <input
                  id="ing-max-pages"
                  type="number"
                  min={1}
                  {...ingestionForm.register("maxPageCount")}
                  placeholder="500"
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
                />
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ing-duplicate">
                  Duplicate Handling
                </FieldLabel>
                <select
                  id="ing-duplicate"
                  {...ingestionForm.register("duplicateHandling")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="skip">skip (ignore duplicate)</option>
                  <option value="replace">replace (overwrite existing)</option>
                  <option value="allow">allow (create new version)</option>
                </select>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ing-reindex">Re-index Policy</FieldLabel>
                <select
                  id="ing-reindex"
                  {...ingestionForm.register("reindexPolicy")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="on_update">on update</option>
                  <option value="manual">manual only</option>
                </select>
              </div>

              <div className="space-y-1">
                <FieldLabel htmlFor="ing-retry">
                  Failed-indexing Retry Policy
                </FieldLabel>
                <select
                  id="ing-retry"
                  {...ingestionForm.register("retryPolicy")}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all appearance-none"
                >
                  <option value="never">never</option>
                  <option value="once">retry once</option>
                  <option value="three_times">retry 3 times</option>
                </select>
              </div>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ing-metadata-tags">
                Default Metadata Tags
              </FieldLabel>
              <input
                id="ing-metadata-tags"
                {...ingestionForm.register("defaultMetadataTags")}
                placeholder="internal, knowledge-base"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 transition-all"
              />
              <p className="text-xs text-[#777587]">Comma-separated.</p>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="ing-auto-index"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  Auto-index on upload
                </label>
                <p className="text-xs text-[#464555]">
                  Automatically start indexing when a document is uploaded
                </p>
              </div>
              <ToggleSwitch
                id="ing-auto-index"
                checked={watchedAutoIndex}
                onChange={(v) =>
                  ingestionForm.setValue("autoIndex", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-end gap-3">
              <SaveFeedback state={ingestionSaveState} />
              <button
                type="button"
                onClick={handleDiscardIngestion}
                disabled={ingestionSaveMutation.isPending}
                className="rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleSaveIngestion();
                }}
                disabled={ingestionSaveMutation.isPending}
                aria-label="Save ingestion defaults"
                className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
              >
                {ingestionSaveMutation.isPending
                  ? "Saving…"
                  : "Save ingestion defaults"}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── 5. Admin Controls ── */}
      <section
        className="bg-white border border-[#c7c4d8] rounded-2xl p-6"
        aria-label="Admin controls section"
      >
        <h2 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          Admin-only controls
        </h2>
        {isAdmin ? (
          <div className="space-y-3">
            <p className="text-sm text-[#4d4963]">
              Administrative security and organization controls are available to
              owner/admin roles.
            </p>
            <Link
              href="/admin"
              className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              Open admin surface
            </Link>
          </div>
        ) : (
          <ForbiddenState
            compact
            title="Admin controls restricted"
            description="Your current role does not permit viewing or modifying organization security controls."
            backHref="/dashboard"
            backLabel="Back to dashboard"
          />
        )}
      </section>

      {/* ── 6. Danger Zone (owner only) ── */}
      {isOwner && (
        <section
          className="bg-white border border-rose-200 rounded-2xl p-6"
          aria-label="Danger zone section"
        >
          <div className="flex items-center gap-3 mb-2">
            <AlertTriangle
              size={20}
              className="text-rose-600"
              aria-hidden="true"
            />
            <h2 className="text-lg font-semibold text-rose-700">Danger Zone</h2>
          </div>
          <p className="mb-6 text-sm text-[#464555]">
            These actions are irreversible and affect all documents, chunks,
            vectors, object files, chats, evaluations, and audit logs associated
            with this organization.
          </p>

          <div className="space-y-4">
            {/* Transfer ownership */}
            {capabilities.transferOwnershipEnabled ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50/30 p-4">
                <p className="mb-2 text-sm font-semibold text-rose-700">
                  Transfer ownership
                </p>
                <p className="mb-3 text-xs text-[#464555]">
                  Transfer organization ownership to another user. You will be
                  downgraded to admin.
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    type="text"
                    value={transferTarget}
                    onChange={(e) => setTransferTarget(e.target.value)}
                    placeholder="Target user ID"
                    disabled={isDangerBusy}
                    aria-label="Transfer ownership target user ID"
                    className="flex-1 rounded-xl border border-rose-200 bg-white px-3 py-2 text-sm outline-none focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 disabled:opacity-60"
                  />
                  <button
                    type="button"
                    disabled={!transferTarget.trim() || isDangerBusy}
                    onClick={() => {
                      const target = transferTarget.trim();
                      if (!target) return;
                      const confirmed = window.confirm(
                        `Transfer ownership to user "${target}"? You will be downgraded to admin.`,
                      );
                      if (!confirmed) return;
                      setDangerState(null);
                      transferMutation.mutate(target);
                    }}
                    className="shrink-0 rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                  >
                    {transferMutation.isPending
                      ? "Transferring…"
                      : "Transfer ownership"}
                  </button>
                </div>
              </div>
            ) : (
              <UnavailableRow
                label="Transfer ownership"
                description="Transfer organization ownership to another user."
              />
            )}

            {/* Archive workspace */}
            {capabilities.archiveEnabled ? (
              <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50/30 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-rose-700">
                    Archive workspace
                  </p>
                  <p className="text-xs text-[#464555]">
                    Make this workspace read-only. Members retain access but
                    cannot make changes.
                  </p>
                </div>
                <button
                  type="button"
                  disabled={isDangerBusy}
                  onClick={() => {
                    const confirmed = window.confirm(
                      "Archive this workspace? It will become read-only for all members.",
                    );
                    if (!confirmed) return;
                    setDangerState(null);
                    archiveMutation.mutate();
                  }}
                  className="shrink-0 rounded-xl border border-rose-300 px-3 py-1.5 text-sm font-semibold text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                >
                  {archiveMutation.isPending ? "Archiving…" : "Archive"}
                </button>
              </div>
            ) : (
              <UnavailableRow
                label="Archive workspace"
                description="Make this workspace read-only."
              />
            )}

            {/* Export workspace data */}
            {capabilities.exportEnabled ? (
              <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50/30 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-rose-700">
                    Export workspace data
                  </p>
                  <p className="text-xs text-[#464555]">
                    Export all documents, metadata, and settings. You will
                    receive a download link.
                  </p>
                </div>
                <button
                  type="button"
                  disabled={isDangerBusy}
                  onClick={() => {
                    const confirmed = window.confirm(
                      "Request an export of all workspace data?",
                    );
                    if (!confirmed) return;
                    setDangerState(null);
                    exportMutation.mutate();
                  }}
                  className="shrink-0 rounded-xl border border-rose-300 px-3 py-1.5 text-sm font-semibold text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                >
                  {exportMutation.isPending ? "Requesting…" : "Export data"}
                </button>
              </div>
            ) : (
              <UnavailableRow
                label="Export workspace data"
                description="Export all documents, metadata, and settings."
              />
            )}

            {/* Delete organization */}
            {capabilities.deleteEnabled ? (
              <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-300 bg-rose-50 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-rose-700">
                    Delete organization
                  </p>
                  <p className="text-xs text-[#464555]">
                    Permanently delete this organization and all associated
                    documents, chunks, vectors, object files, chats, evaluations,
                    and audit logs. This cannot be undone.
                  </p>
                </div>
                <button
                  type="button"
                  disabled={isDangerBusy}
                  onClick={() => {
                    const orgName =
                      session?.organizationName ?? "this organization";
                    const confirmed = window.confirm(
                      `Permanently delete "${orgName}"? All documents, chunks, vectors, chats, evaluations, and audit logs will be permanently removed. This cannot be undone.`,
                    );
                    if (!confirmed) return;
                    setDangerState(null);
                    deleteMutation.mutate();
                  }}
                  className="shrink-0 rounded-xl bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                >
                  {deleteMutation.isPending ? "Deleting…" : "Delete"}
                </button>
              </div>
            ) : (
              <UnavailableRow
                label="Delete organization"
                description="Permanently delete this organization and all associated data."
              />
            )}
          </div>

          {dangerState ? (
            <div className="mt-4">
              <SaveFeedback state={dangerState} />
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
