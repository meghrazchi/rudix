import { apiRequest } from "@/lib/api/request";
import type { AppRole } from "@/lib/auth-session";

export type TeamMemberRole = AppRole;
export type TeamInviteRole = Exclude<AppRole, "owner">;

export type TeamMemberStatus =
  | "active"
  | "invited"
  | "disabled"
  | "suspended"
  | "unknown";

export type TeamMember = {
  member_id: string;
  user_id: string | null;
  name: string;
  email: string;
  role: TeamMemberRole;
  status: TeamMemberStatus;
  created_at: string | null;
  updated_at: string | null;
};

export type TeamMemberListResponse = {
  items: TeamMember[];
  total: number;
  limit: number;
  offset: number;
};

export type TeamMemberListParams = {
  limit?: number;
  offset?: number;
};

export type InviteTeamMemberRequest = {
  email: string;
  role: TeamInviteRole;
};

export type InviteTeamMemberResponse = {
  member: TeamMember;
  invited: boolean;
};

export type UpdateTeamMemberRoleRequest = {
  role: TeamInviteRole;
};

export type TeamCapabilities = {
  listMembersEnabled: boolean;
  inviteEnabled: boolean;
  updateRoleEnabled: boolean;
  removeMemberEnabled: boolean;
};

export class TeamEndpointUnavailableError extends Error {
  readonly endpointKey: keyof TeamCapabilities;

  constructor(endpointKey: keyof TeamCapabilities) {
    super("Team membership endpoint is not configured");
    this.name = "TeamEndpointUnavailableError";
    this.endpointKey = endpointKey;
  }
}

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function resolveTemplateEndpoint(
  template: string | null,
  memberId: string,
): string | null {
  if (!template) {
    return null;
  }
  if (template.includes("{memberId}")) {
    return template.replaceAll("{memberId}", encodeURIComponent(memberId));
  }
  if (template.endsWith("/")) {
    return `${template}${encodeURIComponent(memberId)}`;
  }
  return `${template}/${encodeURIComponent(memberId)}`;
}

function normalizeRole(value: unknown): TeamMemberRole {
  if (
    value === "owner" ||
    value === "admin" ||
    value === "member" ||
    value === "viewer"
  ) {
    return value;
  }
  return "viewer";
}

function normalizeStatus(value: unknown): TeamMemberStatus {
  if (
    value === "active" ||
    value === "invited" ||
    value === "disabled" ||
    value === "suspended"
  ) {
    return value;
  }
  return "unknown";
}

function normalizeMember(value: unknown, index: number): TeamMember {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};

  const memberId =
    typeof raw.member_id === "string" && raw.member_id.trim().length > 0
      ? raw.member_id.trim()
      : `member-${index + 1}`;

  const email =
    typeof raw.email === "string" && raw.email.trim().length > 0
      ? raw.email.trim()
      : "unknown@example.com";

  return {
    member_id: memberId,
    user_id:
      typeof raw.user_id === "string" && raw.user_id.trim().length > 0
        ? raw.user_id.trim()
        : null,
    name:
      typeof raw.name === "string" && raw.name.trim().length > 0
        ? raw.name.trim()
        : email,
    email,
    role: normalizeRole(raw.role),
    status: normalizeStatus(raw.status),
    created_at:
      typeof raw.created_at === "string" && raw.created_at.trim().length > 0
        ? raw.created_at.trim()
        : null,
    updated_at:
      typeof raw.updated_at === "string" && raw.updated_at.trim().length > 0
        ? raw.updated_at.trim()
        : null,
  };
}

function normalizeMemberListResponse(payload: unknown): TeamMemberListResponse {
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items)
    ? raw.items.map((item, index) => normalizeMember(item, index))
    : [];

  const total =
    typeof raw.total === "number" && Number.isFinite(raw.total)
      ? raw.total
      : items.length;
  const limit =
    typeof raw.limit === "number" && Number.isFinite(raw.limit)
      ? raw.limit
      : items.length;
  const offset =
    typeof raw.offset === "number" && Number.isFinite(raw.offset)
      ? raw.offset
      : 0;

  return {
    items,
    total,
    limit,
    offset,
  };
}

function normalizeInviteResponse(payload: unknown): InviteTeamMemberResponse {
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const member = normalizeMember(raw.member ?? raw, 0);
  return {
    member,
    invited: raw.invited !== false,
  };
}

function getTeamEndpoints() {
  return {
    listMembersUrl: trimToNull(process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL),
    inviteUrl: trimToNull(process.env.NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL),
    updateRoleTemplate: trimToNull(
      process.env.NEXT_PUBLIC_TEAM_MEMBER_ROLE_UPDATE_URL_TEMPLATE,
    ),
    removeMemberTemplate: trimToNull(
      process.env.NEXT_PUBLIC_TEAM_MEMBER_REMOVE_URL_TEMPLATE,
    ),
  };
}

export function getTeamCapabilities(): TeamCapabilities {
  const endpoints = getTeamEndpoints();
  return {
    listMembersEnabled: Boolean(endpoints.listMembersUrl),
    inviteEnabled: Boolean(endpoints.inviteUrl),
    updateRoleEnabled: Boolean(endpoints.updateRoleTemplate),
    removeMemberEnabled: Boolean(endpoints.removeMemberTemplate),
  };
}

export function isTeamEndpointUnavailableError(
  error: unknown,
): error is TeamEndpointUnavailableError {
  return error instanceof TeamEndpointUnavailableError;
}

export async function listTeamMembers(
  params: TeamMemberListParams = {},
): Promise<TeamMemberListResponse> {
  const { listMembersUrl } = getTeamEndpoints();
  if (!listMembersUrl) {
    throw new TeamEndpointUnavailableError("listMembersEnabled");
  }

  const limit =
    typeof params.limit === "number" &&
    Number.isFinite(params.limit) &&
    params.limit > 0
      ? Math.floor(params.limit)
      : undefined;
  const offset =
    typeof params.offset === "number" &&
    Number.isFinite(params.offset) &&
    params.offset >= 0
      ? Math.floor(params.offset)
      : undefined;

  const payload = await apiRequest<unknown>(listMembersUrl, {
    method: "GET",
    query: {
      limit,
      offset,
    },
    retry: false,
  });
  return normalizeMemberListResponse(payload);
}

export async function inviteTeamMember(
  request: InviteTeamMemberRequest,
): Promise<InviteTeamMemberResponse> {
  const { inviteUrl } = getTeamEndpoints();
  if (!inviteUrl) {
    throw new TeamEndpointUnavailableError("inviteEnabled");
  }
  const payload = await apiRequest<unknown>(inviteUrl, {
    method: "POST",
    json: {
      email: request.email,
      role: request.role,
    },
    retry: false,
  });
  return normalizeInviteResponse(payload);
}

export async function updateTeamMemberRole(
  memberId: string,
  request: UpdateTeamMemberRoleRequest,
): Promise<TeamMember> {
  const { updateRoleTemplate } = getTeamEndpoints();
  const url = resolveTemplateEndpoint(updateRoleTemplate, memberId);
  if (!url) {
    throw new TeamEndpointUnavailableError("updateRoleEnabled");
  }
  const payload = await apiRequest<unknown>(url, {
    method: "PATCH",
    json: {
      role: request.role,
    },
    retry: false,
  });
  return normalizeMember(
    (payload as Record<string, unknown>).member ?? payload,
    0,
  );
}

export async function removeTeamMember(
  memberId: string,
): Promise<{ removed: boolean }> {
  const { removeMemberTemplate } = getTeamEndpoints();
  const url = resolveTemplateEndpoint(removeMemberTemplate, memberId);
  if (!url) {
    throw new TeamEndpointUnavailableError("removeMemberEnabled");
  }
  await apiRequest<unknown>(url, {
    method: "DELETE",
    retry: false,
  });
  return { removed: true };
}
