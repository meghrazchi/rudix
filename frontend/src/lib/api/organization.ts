import { apiRequest } from "@/lib/api/request";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

export type OrganizationCapabilities = {
  profileEnabled: boolean;
  settingsEnabled: boolean;
  ingestionEnabled: boolean;
  transferOwnershipEnabled: boolean;
  archiveEnabled: boolean;
  exportEnabled: boolean;
  deleteEnabled: boolean;
};

export type OrganizationProfile = {
  id: string | null;
  name: string;
  slug: string;
  primary_domain: string | null;
  domain_allowlist: string[];
  support_email: string | null;
  description: string | null;
  created_at: string | null;
  plan: string | null;
};

export type OrganizationSettings = {
  default_member_role: "member" | "viewer";
  invite_only: boolean;
  allowed_email_domains: string[];
  default_document_visibility: "public" | "private";
  default_collection: string | null;
  retention_days: number | null;
  source_download: "all" | "admins" | "none";
  evaluation_access: boolean;
  agentic_access: boolean;
  mcp_access: boolean;
};

export type IngestionDefaults = {
  allowed_file_types: string[];
  max_upload_size_mb: number | null;
  max_page_count: number | null;
  duplicate_handling: "allow" | "skip" | "replace";
  auto_index: boolean;
  reindex_policy: "on_update" | "manual";
  retry_policy: "never" | "once" | "three_times";
  default_metadata_tags: string[];
};

export class OrganizationEndpointUnavailableError extends Error {
  readonly endpointKey: keyof OrganizationCapabilities;

  constructor(endpointKey: keyof OrganizationCapabilities) {
    super("Organization endpoint is not configured");
    this.name = "OrganizationEndpointUnavailableError";
    this.endpointKey = endpointKey;
  }
}

function getOrgEndpoints() {
  return {
    profileUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_PROFILE_URL),
    settingsUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_SETTINGS_URL),
    ingestionUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_INGESTION_URL),
    transferOwnershipUrl: trimToNull(
      process.env.NEXT_PUBLIC_ORGANIZATION_TRANSFER_OWNERSHIP_URL,
    ),
    archiveUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_ARCHIVE_URL),
    exportUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_EXPORT_URL),
    deleteUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_DELETE_URL),
  };
}

export function getOrganizationCapabilities(): OrganizationCapabilities {
  const e = getOrgEndpoints();
  const allowUnavailable =
    getFrontendRuntimeConfig().features.unavailableBackendEndpoints;

  if (!allowUnavailable) {
    const core = Boolean(e.profileUrl && e.settingsUrl && e.ingestionUrl);
    return {
      profileEnabled: core,
      settingsEnabled: core,
      ingestionEnabled: core,
      transferOwnershipEnabled: core && Boolean(e.transferOwnershipUrl),
      archiveEnabled: core && Boolean(e.archiveUrl),
      exportEnabled: core && Boolean(e.exportUrl),
      deleteEnabled: core && Boolean(e.deleteUrl),
    };
  }

  return {
    profileEnabled: Boolean(e.profileUrl),
    settingsEnabled: Boolean(e.settingsUrl),
    ingestionEnabled: Boolean(e.ingestionUrl),
    transferOwnershipEnabled: Boolean(e.transferOwnershipUrl),
    archiveEnabled: Boolean(e.archiveUrl),
    exportEnabled: Boolean(e.exportUrl),
    deleteEnabled: Boolean(e.deleteUrl),
  };
}

export function isOrganizationEndpointUnavailableError(
  error: unknown,
): error is OrganizationEndpointUnavailableError {
  return error instanceof OrganizationEndpointUnavailableError;
}

type RawRecord = Record<string, unknown>;

function toRaw(payload: unknown): RawRecord {
  return payload !== null &&
    typeof payload === "object" &&
    !Array.isArray(payload)
    ? (payload as RawRecord)
    : {};
}

function asString(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function asStringOrNull(v: unknown): string | null {
  if (typeof v === "string" && v.trim().length > 0) return v.trim();
  return null;
}

function asStringList(v: unknown): string[] {
  if (Array.isArray(v)) {
    return v.filter((x): x is string => typeof x === "string");
  }
  if (typeof v === "string" && v.trim()) {
    return v
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

function asBoolean(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function asPositiveNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return v;
  return null;
}

function asEnum<T extends string>(
  v: unknown,
  options: readonly T[],
  fallback: T,
): T {
  return (options as readonly string[]).includes(v as string)
    ? (v as T)
    : fallback;
}

function normalizeProfile(payload: unknown): OrganizationProfile {
  const r = toRaw(payload);
  return {
    id: asStringOrNull(r.id),
    name: asString(r.name),
    slug: asString(r.slug),
    primary_domain: asStringOrNull(r.primary_domain),
    domain_allowlist: asStringList(r.domain_allowlist),
    support_email: asStringOrNull(r.support_email),
    description: asStringOrNull(r.description),
    created_at: asStringOrNull(r.created_at),
    plan: asStringOrNull(r.plan),
  };
}

function normalizeSettings(payload: unknown): OrganizationSettings {
  const r = toRaw(payload);
  return {
    default_member_role: asEnum(
      r.default_member_role,
      ["member", "viewer"] as const,
      "member",
    ),
    invite_only: asBoolean(r.invite_only, false),
    allowed_email_domains: asStringList(r.allowed_email_domains),
    default_document_visibility: asEnum(
      r.default_document_visibility,
      ["public", "private"] as const,
      "private",
    ),
    default_collection: asStringOrNull(r.default_collection),
    retention_days: asPositiveNumber(r.retention_days),
    source_download: asEnum(
      r.source_download,
      ["all", "admins", "none"] as const,
      "admins",
    ),
    evaluation_access: asBoolean(r.evaluation_access, false),
    agentic_access: asBoolean(r.agentic_access, false),
    mcp_access: asBoolean(r.mcp_access, false),
  };
}

function normalizeIngestionDefaults(payload: unknown): IngestionDefaults {
  const r = toRaw(payload);
  return {
    allowed_file_types: asStringList(r.allowed_file_types),
    max_upload_size_mb: asPositiveNumber(r.max_upload_size_mb),
    max_page_count: asPositiveNumber(r.max_page_count),
    duplicate_handling: asEnum(
      r.duplicate_handling,
      ["allow", "skip", "replace"] as const,
      "skip",
    ),
    auto_index: asBoolean(r.auto_index, true),
    reindex_policy: asEnum(
      r.reindex_policy,
      ["on_update", "manual"] as const,
      "on_update",
    ),
    retry_policy: asEnum(
      r.retry_policy,
      ["never", "once", "three_times"] as const,
      "once",
    ),
    default_metadata_tags: asStringList(r.default_metadata_tags),
  };
}

export async function getOrganizationProfile(): Promise<OrganizationProfile> {
  const { profileUrl } = getOrgEndpoints();
  if (!profileUrl)
    throw new OrganizationEndpointUnavailableError("profileEnabled");
  const payload = await apiRequest<unknown>(profileUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeProfile(payload);
}

export async function updateOrganizationProfile(
  data: Partial<
    Pick<
      OrganizationProfile,
      | "name"
      | "slug"
      | "primary_domain"
      | "domain_allowlist"
      | "support_email"
      | "description"
    >
  >,
): Promise<OrganizationProfile> {
  const { profileUrl } = getOrgEndpoints();
  if (!profileUrl)
    throw new OrganizationEndpointUnavailableError("profileEnabled");
  const payload = await apiRequest<unknown>(profileUrl, {
    method: "PATCH",
    json: data,
    retry: false,
  });
  return normalizeProfile(payload);
}

export async function getOrganizationSettings(): Promise<OrganizationSettings> {
  const { settingsUrl } = getOrgEndpoints();
  if (!settingsUrl)
    throw new OrganizationEndpointUnavailableError("settingsEnabled");
  const payload = await apiRequest<unknown>(settingsUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeSettings(payload);
}

export async function updateOrganizationSettings(
  data: Partial<OrganizationSettings>,
): Promise<OrganizationSettings> {
  const { settingsUrl } = getOrgEndpoints();
  if (!settingsUrl)
    throw new OrganizationEndpointUnavailableError("settingsEnabled");
  const payload = await apiRequest<unknown>(settingsUrl, {
    method: "PATCH",
    json: data,
    retry: false,
  });
  return normalizeSettings(payload);
}

export async function getIngestionDefaults(): Promise<IngestionDefaults> {
  const { ingestionUrl } = getOrgEndpoints();
  if (!ingestionUrl)
    throw new OrganizationEndpointUnavailableError("ingestionEnabled");
  const payload = await apiRequest<unknown>(ingestionUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeIngestionDefaults(payload);
}

export async function updateIngestionDefaults(
  data: Partial<IngestionDefaults>,
): Promise<IngestionDefaults> {
  const { ingestionUrl } = getOrgEndpoints();
  if (!ingestionUrl)
    throw new OrganizationEndpointUnavailableError("ingestionEnabled");
  const payload = await apiRequest<unknown>(ingestionUrl, {
    method: "PATCH",
    json: data,
    retry: false,
  });
  return normalizeIngestionDefaults(payload);
}

export async function transferOwnership(toUserId: string): Promise<void> {
  const { transferOwnershipUrl } = getOrgEndpoints();
  if (!transferOwnershipUrl)
    throw new OrganizationEndpointUnavailableError("transferOwnershipEnabled");
  await apiRequest<unknown>(transferOwnershipUrl, {
    method: "POST",
    json: { to_user_id: toUserId },
    retry: false,
  });
}

export async function archiveOrganization(): Promise<void> {
  const { archiveUrl } = getOrgEndpoints();
  if (!archiveUrl)
    throw new OrganizationEndpointUnavailableError("archiveEnabled");
  await apiRequest<unknown>(archiveUrl, { method: "POST", retry: false });
}

export async function exportOrganizationData(): Promise<{
  download_url: string | null;
}> {
  const { exportUrl } = getOrgEndpoints();
  if (!exportUrl)
    throw new OrganizationEndpointUnavailableError("exportEnabled");
  const payload = await apiRequest<unknown>(exportUrl, {
    method: "POST",
    retry: false,
  });
  const r = toRaw(payload);
  return { download_url: asStringOrNull(r.download_url) };
}

export async function deleteOrganization(): Promise<void> {
  const { deleteUrl } = getOrgEndpoints();
  if (!deleteUrl)
    throw new OrganizationEndpointUnavailableError("deleteEnabled");
  await apiRequest<unknown>(deleteUrl, { method: "DELETE", retry: false });
}
