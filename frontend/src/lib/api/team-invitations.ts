import { normalizeRole, normalizeStatus } from "@/lib/api/team";
import type { TeamMemberRole, TeamMemberStatus } from "@/lib/api/team";
import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type InvitationStatus = "pending" | "accepted" | "expired" | "revoked";

export type OrganizationInvitation = Served<
  Schemas["OrganizationInvitationResponse"]
>;

export type InvitationListResponse = Overlay<
  Served<Schemas["OrganizationInvitationListResponse"]>,
  { items: OrganizationInvitation[] }
>;

export type ResendInvitationResponse = Served<
  Schemas["ResendInvitationResponse"]
>;

export type RevokeInvitationResponse = Served<
  Schemas["RevokeInvitationResponse"]
>;

export type AcceptInvitationResponse = Served<
  Schemas["AcceptInvitationResponse"]
>;

export type TeamMemberDetail = Overlay<
  Served<Schemas["TeamMemberDetailResponse"]>,
  { role: TeamMemberRole; status: TeamMemberStatus }
>;

function trimToNull(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeInvitation(
  raw: Record<string, unknown>,
): OrganizationInvitation {
  return {
    invitation_id:
      typeof raw.invitation_id === "string" ? raw.invitation_id : "",
    organization_id:
      typeof raw.organization_id === "string" ? raw.organization_id : "",
    email: typeof raw.email === "string" ? raw.email : "",
    role: typeof raw.role === "string" ? raw.role : "member",
    status: (["pending", "accepted", "expired", "revoked"].includes(
      raw.status as string,
    )
      ? raw.status
      : "pending") as InvitationStatus,
    expires_at: typeof raw.expires_at === "string" ? raw.expires_at : "",
    invited_by_name:
      typeof raw.invited_by_name === "string" ? raw.invited_by_name : null,
    resend_count: typeof raw.resend_count === "number" ? raw.resend_count : 0,
    last_sent_at:
      typeof raw.last_sent_at === "string" ? raw.last_sent_at : null,
    accepted_at: typeof raw.accepted_at === "string" ? raw.accepted_at : null,
    revoked_at: typeof raw.revoked_at === "string" ? raw.revoked_at : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
}

function getInvitationsBaseUrl(): string | null {
  return trimToNull(process.env.NEXT_PUBLIC_TEAM_INVITATIONS_URL);
}

function getInvitationActionUrl(
  invitationId: string,
  action: "resend" | "revoke",
): string | null {
  const base = getInvitationsBaseUrl();
  if (!base) return null;
  return `${base.replace(/\/$/, "")}/${encodeURIComponent(invitationId)}/${action}`;
}

export async function listInvitations(params?: {
  limit?: number;
  offset?: number;
}): Promise<InvitationListResponse> {
  const url = getInvitationsBaseUrl();
  if (!url) {
    return { items: [], total: 0, limit: 50, offset: 0 };
  }
  const payload = await apiRequest<unknown>(url, {
    method: "GET",
    query: {
      limit: params?.limit,
      offset: params?.offset,
    },
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items)
    ? raw.items
        .filter((i): i is Record<string, unknown> => Boolean(i))
        .map(normalizeInvitation)
    : [];
  return {
    items,
    total: typeof raw.total === "number" ? raw.total : items.length,
    limit: typeof raw.limit === "number" ? raw.limit : 50,
    offset: typeof raw.offset === "number" ? raw.offset : 0,
  };
}

export async function resendInvitation(
  invitationId: string,
): Promise<ResendInvitationResponse> {
  const url = getInvitationActionUrl(invitationId, "resend");
  if (!url) {
    throw new Error("Team invitations endpoint not configured");
  }
  const payload = await apiRequest<unknown>(url, {
    method: "POST",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    invitation_id:
      typeof raw.invitation_id === "string" ? raw.invitation_id : invitationId,
    resent: raw.resent !== false,
  };
}

export async function revokeInvitation(
  invitationId: string,
): Promise<RevokeInvitationResponse> {
  const url = getInvitationActionUrl(invitationId, "revoke");
  if (!url) {
    throw new Error("Team invitations endpoint not configured");
  }
  const payload = await apiRequest<unknown>(url, {
    method: "POST",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    invitation_id:
      typeof raw.invitation_id === "string" ? raw.invitation_id : invitationId,
    revoked: raw.revoked !== false,
  };
}

export async function acceptInvitation(
  token: string,
  password: string,
): Promise<AcceptInvitationResponse> {
  const url = trimToNull(process.env.NEXT_PUBLIC_TEAM_INVITATIONS_ACCEPT_URL);
  if (!url) {
    throw new Error("Accept invitation endpoint not configured");
  }
  const payload = await apiRequest<unknown>(url, {
    method: "POST",
    json: { token, password },
    attachAuth: false,
    attachOrganizationId: false,
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    accepted: raw.accepted !== false,
    email: typeof raw.email === "string" ? raw.email : "",
    role: typeof raw.role === "string" ? raw.role : "member",
    organization_name:
      typeof raw.organization_name === "string" ? raw.organization_name : null,
  };
}

export async function getTeamMemberDetail(
  memberId: string,
): Promise<TeamMemberDetail> {
  const baseUrl = trimToNull(process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL);
  if (!baseUrl) {
    throw new Error("Team members endpoint not configured");
  }
  const url = `${baseUrl.replace(/\/$/, "")}/${encodeURIComponent(memberId)}`;
  const payload = await apiRequest<unknown>(url, {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    member_id: typeof raw.member_id === "string" ? raw.member_id : memberId,
    user_id: typeof raw.user_id === "string" ? raw.user_id : null,
    name: typeof raw.name === "string" ? raw.name : "",
    email: typeof raw.email === "string" ? raw.email : "",
    role: normalizeRole(raw.role),
    custom_role_id:
      typeof raw.custom_role_id === "string" ? raw.custom_role_id : null,
    status: normalizeStatus(raw.status),
    is_active: raw.is_active !== false,
    provisioned_by:
      typeof raw.provisioned_by === "string" ? raw.provisioned_by : "manual",
    created_at: typeof raw.created_at === "string" ? raw.created_at : null,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
  };
}

export async function deactivateTeamMember(
  memberId: string,
): Promise<TeamMemberDetail> {
  const baseUrl = trimToNull(process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL);
  if (!baseUrl) {
    throw new Error("Team members endpoint not configured");
  }
  const url = `${baseUrl.replace(/\/$/, "")}/${encodeURIComponent(memberId)}/deactivate`;
  const payload = await apiRequest<unknown>(url, {
    method: "POST",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    member_id: typeof raw.member_id === "string" ? raw.member_id : memberId,
    user_id: typeof raw.user_id === "string" ? raw.user_id : null,
    name: typeof raw.name === "string" ? raw.name : "",
    email: typeof raw.email === "string" ? raw.email : "",
    role: normalizeRole(raw.role),
    custom_role_id:
      typeof raw.custom_role_id === "string" ? raw.custom_role_id : null,
    status: normalizeStatus(raw.status),
    is_active: raw.is_active !== false,
    provisioned_by:
      typeof raw.provisioned_by === "string" ? raw.provisioned_by : "manual",
    created_at: typeof raw.created_at === "string" ? raw.created_at : null,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
  };
}
