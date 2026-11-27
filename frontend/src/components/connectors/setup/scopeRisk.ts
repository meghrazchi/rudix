// ── Scope-risk analysis (mirrors backend logic for instant feedback) ──────────

export const WRITE_SCOPE_KEYWORDS = [
  "write",
  "delete",
  "modify",
  "create",
  "update",
];
export const ADMIN_SCOPE_KEYWORDS = ["admin"];
export const ORG_WIDE_SCOPE_SUFFIXES = [".all", ":all", "_all"];

export const PROVIDER_ORG_WIDE_SCOPES: Record<string, string[]> = {
  google_drive: [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
  ],
  "microsoft-sharepoint-onedrive": ["Sites.Read.All", "Files.Read.All"],
};

export type ScopeRisk =
  | "write_permission"
  | "admin_scope"
  | "org_wide_access"
  | "broad_read";

export function detectScopeRisks(
  scopes: string[],
  providerKey: string,
  configValues: Record<string, string | boolean>,
): { code: ScopeRisk; message: string; scope: string }[] {
  const warnings: { code: ScopeRisk; message: string; scope: string }[] = [];

  const hasFilter = [
    "folder_ids",
    "site_ids",
    "drive_ids",
    "space_keys",
    "project_keys",
  ].some((k) => {
    const v = configValues[k];
    return typeof v === "string" ? v.trim().length > 0 : Boolean(v);
  });

  for (const scope of scopes) {
    const lower = scope.toLowerCase();
    if (WRITE_SCOPE_KEYWORDS.some((kw) => lower.includes(kw))) {
      warnings.push({
        code: "write_permission",
        message: `'${scope}' grants write or delete access — Rudix only needs read-only scopes.`,
        scope,
      });
      continue;
    }
    if (ADMIN_SCOPE_KEYWORDS.some((kw) => lower.includes(kw))) {
      warnings.push({
        code: "admin_scope",
        message: `'${scope}' grants admin-level access beyond what indexing requires.`,
        scope,
      });
      continue;
    }
    const providerOrgWide = PROVIDER_ORG_WIDE_SCOPES[providerKey] ?? [];
    if (providerOrgWide.includes(scope) && !hasFilter) {
      warnings.push({
        code: "org_wide_access",
        message: `'${scope}' grants access to your entire organisation with no source filter. Consider restricting to specific folders or sites.`,
        scope,
      });
      continue;
    }
    if (ORG_WIDE_SCOPE_SUFFIXES.some((sfx) => lower.endsWith(sfx))) {
      warnings.push({
        code: "broad_read",
        message: `'${scope}' appears to grant broad read access — confirm this is the minimum required scope.`,
        scope,
      });
    }
  }
  return warnings;
}
