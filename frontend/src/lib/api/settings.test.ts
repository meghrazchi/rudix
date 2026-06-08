import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api/errors";
import {
  getMe,
  updateMe,
  getMyPreferences,
  updateMyPreferences,
  signOutAllDevices,
  deletePersonalAccount,
  getProfileCapabilities,
  ProfileEndpointUnavailableError,
  isProfileEndpointUnavailableError,
} from "@/lib/api/profile";
import {
  getSessions,
  revokeSession,
  revokeAllOtherSessions,
  getLoginPolicy,
  updateLoginPolicy,
  getSecurityPosture,
  getRecentAuditEvents,
  getSecurityCapabilities,
  SecurityEndpointUnavailableError,
  isSecurityEndpointUnavailableError,
} from "@/lib/api/security";
import {
  getBillingCapabilities,
  getBillingPlanInfo,
  createBillingPortalSession,
  updateBillingContact,
  BillingEndpointUnavailableError,
  isBillingEndpointUnavailableError,
} from "@/lib/api/billing";
import {
  listTeamMembers,
  inviteTeamMember,
  updateTeamMemberRole,
  removeTeamMember,
  getTeamCapabilities,
  TeamEndpointUnavailableError,
  isTeamEndpointUnavailableError,
} from "@/lib/api/team";

const fetchMock = vi.fn<typeof fetch>();
const originalEnv = { ...process.env };

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  process.env = { ...originalEnv };
});

afterEach(() => {
  vi.unstubAllGlobals();
  process.env = { ...originalEnv };
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ── Profile ───────────────────────────────────────────────────────────────────

describe("getProfileCapabilities", () => {
  it("reports all enabled when env vars are set", () => {
    process.env.NEXT_PUBLIC_PROFILE_ME_URL = "http://api.test/me";
    process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL =
      "http://api.test/me/prefs";
    process.env.NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL =
      "http://api.test/sign-out-all";
    process.env.NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL =
      "http://api.test/delete";

    const caps = getProfileCapabilities();
    expect(caps.meEnabled).toBe(true);
    expect(caps.preferencesEnabled).toBe(true);
    expect(caps.signOutAllDevicesEnabled).toBe(true);
    expect(caps.deleteAccountEnabled).toBe(true);
  });

  it("reports disabled when env vars are absent", () => {
    delete process.env.NEXT_PUBLIC_PROFILE_ME_URL;
    delete process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL;

    const caps = getProfileCapabilities();
    expect(caps.meEnabled).toBe(false);
    expect(caps.preferencesEnabled).toBe(false);
  });
});

describe("getMe", () => {
  it("returns normalized user profile on success", async () => {
    process.env.NEXT_PUBLIC_PROFILE_ME_URL = "http://api.test/me";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "user-1",
        email: "alice@example.com",
        name: "Alice",
        avatar_url: "https://cdn.example.com/alice.png",
        created_at: "2026-01-01T00:00:00Z",
      }),
    );

    const profile = await getMe();
    expect(profile.id).toBe("user-1");
    expect(profile.email).toBe("alice@example.com");
    expect(profile.name).toBe("Alice");
    expect(profile.avatarUrl).toBe("https://cdn.example.com/alice.png");
  });

  it("throws ProfileEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_PROFILE_ME_URL;
    await expect(getMe()).rejects.toBeInstanceOf(
      ProfileEndpointUnavailableError,
    );
  });

  it("throws ApiClientError on 403", async () => {
    process.env.NEXT_PUBLIC_PROFILE_ME_URL = "http://api.test/me";
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Forbidden" }, 403));
    await expect(getMe()).rejects.toBeInstanceOf(ApiClientError);
  });

  it("throws ApiClientError on 429", async () => {
    process.env.NEXT_PUBLIC_PROFILE_ME_URL = "http://api.test/me";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Too many requests" }, 429),
    );
    await expect(getMe()).rejects.toBeInstanceOf(ApiClientError);
  });
});

describe("updateMe", () => {
  it("sends PATCH with name payload and returns updated profile", async () => {
    process.env.NEXT_PUBLIC_PROFILE_ME_URL = "http://api.test/me";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "user-1", email: "alice@example.com", name: "Bob" }),
    );

    const result = await updateMe({ name: "Bob" });
    expect(result.name).toBe("Bob");

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.method).toBe("PATCH");
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(body.name).toBe("Bob");
  });

  it("throws ProfileEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_PROFILE_ME_URL;
    await expect(updateMe({ name: "Bob" })).rejects.toBeInstanceOf(
      ProfileEndpointUnavailableError,
    );
  });
});

describe("getMyPreferences", () => {
  it("normalizes snake_case fields to camelCase", async () => {
    process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL =
      "http://api.test/me/prefs";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        language: "en",
        date_format: "YYYY-MM-DD",
        keyboard_shortcut_hints: false,
        email_notifications: true,
        digest_frequency: "weekly",
      }),
    );

    const prefs = await getMyPreferences();
    expect(prefs.language).toBe("en");
    expect(prefs.dateFormat).toBe("YYYY-MM-DD");
    expect(prefs.keyboardShortcutHints).toBe(false);
    expect(prefs.emailNotifications).toBe(true);
    expect(prefs.digestFrequency).toBe("weekly");
  });

  it("throws ProfileEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL;
    await expect(getMyPreferences()).rejects.toBeInstanceOf(
      ProfileEndpointUnavailableError,
    );
  });
});

describe("updateMyPreferences", () => {
  it("maps camelCase form values to snake_case payload", async () => {
    process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL =
      "http://api.test/me/prefs";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ language: "de", keyboard_shortcut_hints: true }),
    );

    await updateMyPreferences({
      language: "de",
      keyboardShortcutHints: true,
      landingPage: "/chat",
    });

    const [, init] = fetchMock.mock.calls[0] ?? [];
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(body.language).toBe("de");
    expect(body.keyboard_shortcut_hints).toBe(true);
    expect(body.landing_page).toBe("/chat");
    expect(body.keyboardShortcutHints).toBeUndefined();
  });
});

describe("isProfileEndpointUnavailableError", () => {
  it("returns true for ProfileEndpointUnavailableError instances", () => {
    expect(
      isProfileEndpointUnavailableError(
        new ProfileEndpointUnavailableError("meEnabled"),
      ),
    ).toBe(true);
  });

  it("returns false for generic errors", () => {
    expect(isProfileEndpointUnavailableError(new Error("oops"))).toBe(false);
  });
});

describe("signOutAllDevices", () => {
  it("throws ProfileEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL;
    await expect(signOutAllDevices()).rejects.toBeInstanceOf(
      ProfileEndpointUnavailableError,
    );
  });
});

describe("deletePersonalAccount", () => {
  it("throws ProfileEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL;
    await expect(deletePersonalAccount()).rejects.toBeInstanceOf(
      ProfileEndpointUnavailableError,
    );
  });
});

// ── Security ──────────────────────────────────────────────────────────────────

describe("getSecurityCapabilities", () => {
  it("reports enabled when env vars are set", () => {
    process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL = "http://api.test/sessions";
    process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL =
      "http://api.test/policy";
    process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL = "http://api.test/posture";
    process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL = "http://api.test/audit";

    const caps = getSecurityCapabilities();
    expect(caps.sessionsEnabled).toBe(true);
    expect(caps.loginPolicyEnabled).toBe(true);
    expect(caps.postureEnabled).toBe(true);
    expect(caps.auditEnabled).toBe(true);
  });

  it("reports disabled when env vars are absent", () => {
    delete process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL;
    const caps = getSecurityCapabilities();
    expect(caps.sessionsEnabled).toBe(false);
  });
});

describe("getSessions", () => {
  it("returns a list of normalized sessions", async () => {
    process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL = "http://api.test/sessions";
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: "session-1",
          device: "Chrome on macOS",
          ip_address: "1.2.3.4",
          location: "San Francisco, CA",
          created_at: "2026-05-01T00:00:00Z",
          last_active_at: "2026-06-01T00:00:00Z",
          is_current: true,
        },
      ]),
    );

    const sessions = await getSessions();
    expect(sessions).toHaveLength(1);
    expect(sessions[0]?.id).toBe("session-1");
    expect(sessions[0]?.is_current).toBe(true);
  });

  it("handles items-wrapped responses", async () => {
    process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL = "http://api.test/sessions";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [{ id: "session-2", device: "Firefox", is_current: false }],
      }),
    );

    const sessions = await getSessions();
    expect(sessions).toHaveLength(1);
    expect(sessions[0]?.id).toBe("session-2");
  });

  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL;
    await expect(getSessions()).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });

  it("throws ApiClientError on 403", async () => {
    process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL = "http://api.test/sessions";
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Forbidden" }, 403));
    await expect(getSessions()).rejects.toBeInstanceOf(ApiClientError);
  });
});

describe("revokeSession", () => {
  it("sends DELETE to the constructed URL", async () => {
    process.env.NEXT_PUBLIC_SECURITY_REVOKE_SESSION_URL =
      "http://api.test/sessions";
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 200));

    await revokeSession("session-abc");

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("session-abc");
    expect(init?.method).toBe("DELETE");
  });

  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_REVOKE_SESSION_URL;
    await expect(revokeSession("s")).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });
});

describe("revokeAllOtherSessions", () => {
  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_REVOKE_ALL_SESSIONS_URL;
    await expect(revokeAllOtherSessions()).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });
});

describe("getLoginPolicy", () => {
  it("normalizes login policy response", async () => {
    process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL =
      "http://api.test/policy";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        domain_allowlist: ["acme.com"],
        session_timeout_hours: 8,
        sso_required: true,
        invite_only: false,
        mfa_required: true,
      }),
    );

    const policy = await getLoginPolicy();
    expect(policy.domain_allowlist).toEqual(["acme.com"]);
    expect(policy.session_timeout_hours).toBe(8);
    expect(policy.sso_required).toBe(true);
    expect(policy.mfa_required).toBe(true);
  });

  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL;
    await expect(getLoginPolicy()).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });
});

describe("updateLoginPolicy", () => {
  it("sends PATCH and returns normalized policy", async () => {
    process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL =
      "http://api.test/policy";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ mfa_required: true, sso_required: false }),
    );

    const result = await updateLoginPolicy({ mfa_required: true });
    expect(result.mfa_required).toBe(true);

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.method).toBe("PATCH");
  });

  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL;
    await expect(updateLoginPolicy({})).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });
});

describe("getSecurityPosture", () => {
  it("normalizes posture response", async () => {
    process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL = "http://api.test/posture";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        prompt_injection_protection: true,
        citation_validation: false,
        tenant_isolation: null,
        last_audit_at: "2026-06-01T00:00:00Z",
      }),
    );

    const posture = await getSecurityPosture();
    expect(posture.prompt_injection_protection).toBe(true);
    expect(posture.citation_validation).toBe(false);
    expect(posture.tenant_isolation).toBeNull();
    expect(posture.last_audit_at).toBe("2026-06-01T00:00:00Z");
  });

  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL;
    await expect(getSecurityPosture()).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });
});

describe("getRecentAuditEvents", () => {
  it("returns an empty array for empty responses", async () => {
    process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL = "http://api.test/audit";
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    const events = await getRecentAuditEvents();
    expect(events).toEqual([]);
  });

  it("throws SecurityEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL;
    await expect(getRecentAuditEvents()).rejects.toBeInstanceOf(
      SecurityEndpointUnavailableError,
    );
  });
});

describe("isSecurityEndpointUnavailableError", () => {
  it("returns true for SecurityEndpointUnavailableError instances", () => {
    expect(
      isSecurityEndpointUnavailableError(
        new SecurityEndpointUnavailableError("sessionsEnabled"),
      ),
    ).toBe(true);
  });

  it("returns false for generic errors", () => {
    expect(isSecurityEndpointUnavailableError(new Error("oops"))).toBe(false);
  });
});

// ── Billing ───────────────────────────────────────────────────────────────────

describe("getBillingCapabilities", () => {
  it("includes portalSessionEnabled in capability map", () => {
    process.env.NEXT_PUBLIC_BILLING_PORTAL_SESSION_URL =
      "http://api.test/portal";
    const caps = getBillingCapabilities();
    expect("portalSessionEnabled" in caps).toBe(true);
  });
});

describe("getBillingPlanInfo", () => {
  it("returns normalized plan info on success", async () => {
    process.env.NEXT_PUBLIC_BILLING_PLAN_URL = "http://api.test/billing/plan";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        plan_name: "Enterprise",
        status: "active",
        billing_cycle: "annual",
        seats_used: 12,
        seats_included: 50,
        can_manage_subscription: true,
        can_cancel_plan: false,
      }),
    );

    const plan = await getBillingPlanInfo();
    expect(plan.plan_name).toBe("Enterprise");
    expect(plan.status).toBe("active");
    expect(plan.billing_cycle).toBe("annual");
    expect(plan.can_manage_subscription).toBe(true);
  });

  it("throws BillingEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_BILLING_PLAN_URL;
    await expect(getBillingPlanInfo()).rejects.toBeInstanceOf(
      BillingEndpointUnavailableError,
    );
  });

  it("throws ApiClientError on 429", async () => {
    process.env.NEXT_PUBLIC_BILLING_PLAN_URL = "http://api.test/billing/plan";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Too many requests" }, 429),
    );
    await expect(getBillingPlanInfo()).rejects.toBeInstanceOf(ApiClientError);
  });
});

describe("createBillingPortalSession", () => {
  it("returns portal URL and expiry on success", async () => {
    process.env.NEXT_PUBLIC_BILLING_PORTAL_SESSION_URL =
      "http://api.test/billing/portal";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        url: "https://billing.stripe.com/session/xyz",
        expires_at: "2026-06-03T01:00:00Z",
      }),
    );

    const session = await createBillingPortalSession();
    expect(session.url).toBe("https://billing.stripe.com/session/xyz");
    expect(session.expires_at).toBe("2026-06-03T01:00:00Z");

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.method).toBe("POST");
  });

  it("throws BillingEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_BILLING_PORTAL_SESSION_URL;
    await expect(createBillingPortalSession()).rejects.toBeInstanceOf(
      BillingEndpointUnavailableError,
    );
  });

  it("throws ApiClientError on 403", async () => {
    process.env.NEXT_PUBLIC_BILLING_PORTAL_SESSION_URL =
      "http://api.test/billing/portal";
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Forbidden" }, 403));
    await expect(createBillingPortalSession()).rejects.toBeInstanceOf(
      ApiClientError,
    );
  });
});

describe("updateBillingContact", () => {
  it("sends PATCH and returns normalized contact", async () => {
    process.env.NEXT_PUBLIC_BILLING_CONTACT_UPDATE_URL =
      "http://api.test/billing/contact";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ email: "billing@acme.com", name: "Acme Finance" }),
    );

    const result = await updateBillingContact({ email: "billing@acme.com" });
    expect(result.email).toBe("billing@acme.com");

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.method).toBe("PATCH");
  });

  it("throws BillingEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_BILLING_CONTACT_UPDATE_URL;
    await expect(updateBillingContact({})).rejects.toBeInstanceOf(
      BillingEndpointUnavailableError,
    );
  });
});

describe("isBillingEndpointUnavailableError", () => {
  it("returns true for BillingEndpointUnavailableError instances", () => {
    expect(
      isBillingEndpointUnavailableError(
        new BillingEndpointUnavailableError("planEnabled"),
      ),
    ).toBe(true);
  });

  it("returns false for generic errors", () => {
    expect(isBillingEndpointUnavailableError(new Error("oops"))).toBe(false);
  });
});

// ── Team ──────────────────────────────────────────────────────────────────────

describe("getTeamCapabilities", () => {
  it("reports all disabled when env vars are absent", () => {
    delete process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL;
    delete process.env.NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL;
    delete process.env.NEXT_PUBLIC_TEAM_MEMBER_ROLE_UPDATE_URL_TEMPLATE;
    delete process.env.NEXT_PUBLIC_TEAM_MEMBER_REMOVE_URL_TEMPLATE;
    process.env.NEXT_PUBLIC_RUNTIME_ALLOW_UNAVAILABLE_BACKEND_ENDPOINTS =
      "true";

    const caps = getTeamCapabilities();
    expect(caps.listMembersEnabled).toBe(false);
    expect(caps.inviteEnabled).toBe(false);
    expect(caps.updateRoleEnabled).toBe(false);
    expect(caps.removeMemberEnabled).toBe(false);
  });
});

describe("listTeamMembers", () => {
  it("returns normalized member list on success", async () => {
    process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL =
      "http://api.test/team/members";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            member_id: "m-1",
            user_id: "u-1",
            name: "Alice",
            email: "alice@example.com",
            role: "admin",
            status: "active",
          },
        ],
        total: 1,
        limit: 25,
        offset: 0,
      }),
    );

    const result = await listTeamMembers();
    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.email).toBe("alice@example.com");
    expect(result.items[0]?.role).toBe("admin");
    expect(result.total).toBe(1);
  });

  it("throws TeamEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL;
    await expect(listTeamMembers()).rejects.toBeInstanceOf(
      TeamEndpointUnavailableError,
    );
  });

  it("throws ApiClientError on 403", async () => {
    process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL =
      "http://api.test/team/members";
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Forbidden" }, 403));
    await expect(listTeamMembers()).rejects.toBeInstanceOf(ApiClientError);
  });
});

describe("inviteTeamMember", () => {
  it("sends POST with email and role", async () => {
    process.env.NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL =
      "http://api.test/team/invite";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        member: {
          member_id: "m-2",
          email: "bob@example.com",
          role: "member",
          status: "invited",
          name: "Bob",
        },
        invited: true,
      }),
    );

    const result = await inviteTeamMember({
      email: "bob@example.com",
      role: "member",
    });
    expect(result.invited).toBe(true);
    expect(result.member.email).toBe("bob@example.com");

    const [, init] = fetchMock.mock.calls[0] ?? [];
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(body.email).toBe("bob@example.com");
    expect(body.role).toBe("member");
  });

  it("throws TeamEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL;
    await expect(
      inviteTeamMember({ email: "x@example.com", role: "member" }),
    ).rejects.toBeInstanceOf(TeamEndpointUnavailableError);
  });
});

describe("updateTeamMemberRole", () => {
  it("throws TeamEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_TEAM_MEMBER_ROLE_UPDATE_URL_TEMPLATE;
    await expect(
      updateTeamMemberRole("m-1", { role: "admin" }),
    ).rejects.toBeInstanceOf(TeamEndpointUnavailableError);
  });
});

describe("removeTeamMember", () => {
  it("throws TeamEndpointUnavailableError when endpoint is not configured", async () => {
    delete process.env.NEXT_PUBLIC_TEAM_MEMBER_REMOVE_URL_TEMPLATE;
    await expect(removeTeamMember("m-1")).rejects.toBeInstanceOf(
      TeamEndpointUnavailableError,
    );
  });
});

describe("isTeamEndpointUnavailableError", () => {
  it("returns true for TeamEndpointUnavailableError instances", () => {
    expect(
      isTeamEndpointUnavailableError(
        new TeamEndpointUnavailableError("inviteEnabled"),
      ),
    ).toBe(true);
  });

  it("returns false for generic errors", () => {
    expect(isTeamEndpointUnavailableError(new Error("oops"))).toBe(false);
  });
});
