import type { useTranslations } from "next-intl";

import type { CollectionAccessPolicy } from "@/lib/api/collections";
import type { AppRole } from "@/lib/auth-session";

const COLLECTIONS_PAGE_SIZE = 20;
const COLLECTION_DOCS_PAGE_SIZE = 20;
const COLLECTION_DOCS_INITIAL_LIMIT = 10;
const COLLECTION_PICKER_PAGE_SIZE = 10;

const CARD_ICONS = [
  "inventory_2",
  "account_balance",
  "book_2",
  "layers",
  "hub",
  "category",
  "psychology",
  "school",
  "insights",
  "folder_shared",
  "gavel",
  "support_agent",
  "science",
  "engineering",
  "manage_accounts",
];

function pickIcon(id: string): string {
  let h = 0;
  for (const c of id) h = (h + c.charCodeAt(0)) % CARD_ICONS.length;
  return CARD_ICONS[h]!;
}

type CollectionCapabilities = {
  canCreate: boolean;
  canEdit: boolean;
  canDelete: boolean;
  canManageDocuments: boolean;
  canManagePolicy: boolean;
};

function resolveCollectionCapabilities(
  role: AppRole | undefined,
): CollectionCapabilities {
  const isAdminLike = role === "owner" || role === "admin";
  const isMember = role === "member";
  return {
    canCreate: isAdminLike || isMember,
    canEdit: isAdminLike || isMember,
    canDelete: isAdminLike,
    canManageDocuments: isAdminLike || isMember,
    canManagePolicy: isAdminLike,
  };
}

function formatRelativeDate(
  value: string,
  tc: ReturnType<typeof useTranslations>,
): string {
  try {
    const diff = Date.now() - new Date(value).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 2) return tc("relativeJustNow");
    if (mins < 60) return tc("relativeMinutesAgo", { n: mins });
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return tc("relativeHoursAgo", { n: hrs });
    return tc("relativeDaysAgo", { n: Math.floor(hrs / 24) });
  } catch {
    return "";
  }
}

function accessPolicyLabel(
  policy: CollectionAccessPolicy,
  tc: ReturnType<typeof useTranslations>,
): string {
  switch (policy) {
    case "org_wide":
      return tc("policyLabelOrgWide");
    case "admin_only":
      return tc("policyLabelAdminOnly");
    case "selected_roles":
      return tc("policyLabelSelectedRoles");
    case "selected_members":
      return tc("policyLabelSelectedMembers");
    default:
      return policy;
  }
}

function accessPolicyBadgeClass(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "bg-green-50 text-green-700 border-green-200";
    case "admin_only":
      return "bg-amber-50 text-amber-800 border-amber-200";
    case "selected_roles":
      return "bg-blue-50 text-blue-700 border-blue-200";
    case "selected_members":
      return "bg-violet-50 text-violet-700 border-violet-200";
    default:
      return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

function accessPolicyDescription(
  policy: CollectionAccessPolicy,
  tc: ReturnType<typeof useTranslations>,
): string {
  switch (policy) {
    case "org_wide":
      return tc("policyDescOrgWide");
    case "admin_only":
      return tc("policyDescAdminOnly");
    case "selected_roles":
      return tc("policyDescSelectedRoles");
    case "selected_members":
      return tc("policyDescSelectedMembers");
    default:
      return "";
  }
}

function accessPolicyIcon(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "public";
    case "admin_only":
      return "admin_panel_settings";
    case "selected_roles":
      return "group";
    case "selected_members":
      return "person_check";
    default:
      return "lock";
  }
}

export {
  CARD_ICONS,
  COLLECTIONS_PAGE_SIZE,
  COLLECTION_DOCS_INITIAL_LIMIT,
  COLLECTION_DOCS_PAGE_SIZE,
  COLLECTION_PICKER_PAGE_SIZE,
  accessPolicyBadgeClass,
  accessPolicyDescription,
  accessPolicyIcon,
  accessPolicyLabel,
  formatRelativeDate,
  pickIcon,
  resolveCollectionCapabilities,
};
export type { CollectionCapabilities };
