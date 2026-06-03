/**
 * F193 – Settings backend endpoint contract tests.
 *
 * These tests exercise the settings API client layer directly against MSW
 * mock handlers.  They verify:
 *   1. Happy-path: correct HTTP method, URL, auth header, and normalized data.
 *   2. Capability gate: when env var is unset the client throws the typed
 *      *EndpointUnavailableError before making any HTTP call.
 *   3. 501 response: when the backend stub returns NOT_IMPLEMENTED the client
 *      raises an ApiClientError with status 501.
 *   4. 403/429 responses: client raises ApiClientError with the matching status
 *      so the UI can render the correct Forbidden/RateLimit state.
 */

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { isApiClientError } from "@/lib/api/errors";
import {
  getMe,
  getMyPreferences,
  updateMe,
  updateMyPreferences,
  isProfileEndpointUnavailableError,
} from "@/lib/api/profile";
import {
  getSessions,
  getLoginPolicy,
  getSecurityPosture,
  getRecentAuditEvents,
  isSecurityEndpointUnavailableError,
} from "@/lib/api/security";
import {
  getOrganizationProfile,
  getOrganizationSettings,
  getIngestionDefaults,
  isOrganizationEndpointUnavailableError,
} from "@/lib/api/organization";
import {
  getBillingPlanInfo,
  getBillingUsageSummary,
  getBillingQuotas,
  getInvoices,
  getBillingContact,
  isBillingEndpointUnavailableError,
} from "@/lib/api/billing";
import {
  mockUserProfile,
  mockUserPreferences,
  mockSecuritySessions,
  mockLoginPolicy,
  mockSecurityPosture,
  mockSecurityAuditEvents,
  mockOrganizationProfile,
  mockOrganizationSettings,
  mockIngestionDefaults,
  mockBillingPlanInfo,
  mockBillingUsageSummary,
  mockBillingQuotas,
  mockInvoices,
  mockBillingContact,
} from "@/test/msw/fixtures";

const API_BASE = "http://api.test";

const NOT_IMPLEMENTED_BODY = {
  error_code: "NOT_IMPLEMENTED",
  detail: "This endpoint is not yet implemented.",
};

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = API_BASE;
});
afterEach(() => {
  server.resetHandlers();
  // Reset API base and all settings env vars between tests
  delete process.env.NEXT_PUBLIC_API_URL;
  delete process.env.NEXT_PUBLIC_PROFILE_ME_URL;
  delete process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL;
  delete process.env.NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL;
  delete process.env.NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL;
  delete process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL;
  delete process.env.NEXT_PUBLIC_SECURITY_REVOKE_SESSION_URL;
  delete process.env.NEXT_PUBLIC_SECURITY_REVOKE_ALL_SESSIONS_URL;
  delete process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL;
  delete process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL;
  delete process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL;
  delete process.env.NEXT_PUBLIC_ORGANIZATION_PROFILE_URL;
  delete process.env.NEXT_PUBLIC_ORGANIZATION_SETTINGS_URL;
  delete process.env.NEXT_PUBLIC_ORGANIZATION_INGESTION_URL;
  delete process.env.NEXT_PUBLIC_BILLING_PLAN_URL;
  delete process.env.NEXT_PUBLIC_BILLING_USAGE_URL;
  delete process.env.NEXT_PUBLIC_BILLING_QUOTAS_URL;
  delete process.env.NEXT_PUBLIC_BILLING_INVOICES_URL;
  delete process.env.NEXT_PUBLIC_BILLING_CONTACT_URL;
});
afterAll(() => server.close());

// ── Shared helpers ─────────────────────────────────────────────────────────────

function notImplemented() {
  return HttpResponse.json(NOT_IMPLEMENTED_BODY, { status: 501 });
}

function forbidden() {
  return HttpResponse.json(
    { error_code: "FORBIDDEN", detail: "Insufficient role." },
    { status: 403 },
  );
}

function rateLimited() {
  return HttpResponse.json(
    { error_code: "RATE_LIMITED", detail: "Too many requests." },
    { status: 429 },
  );
}

// ── Profile contracts ──────────────────────────────────────────────────────────

describe("Profile API contracts", () => {
  describe("GET /me", () => {
    it("throws ProfileEndpointUnavailableError when env var is unset", async () => {
      const err = await getMe().catch((e) => e);
      expect(isProfileEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("meEnabled");
    });

    it("returns normalized profile on 200", async () => {
      process.env.NEXT_PUBLIC_PROFILE_ME_URL = "/me";
      server.use(http.get(`${API_BASE}/me`, () => HttpResponse.json(mockUserProfile)));
      const profile = await getMe();
      expect(profile.id).toBe("user-1");
      expect(profile.email).toBe("alice@example.com");
      expect(profile.name).toBe("Alice Example");
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_PROFILE_ME_URL = "/me";
      server.use(http.get(`${API_BASE}/me`, notImplemented));
      const err = await getMe().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });

    it("raises ApiClientError with status 403 on Forbidden", async () => {
      process.env.NEXT_PUBLIC_PROFILE_ME_URL = "/me";
      server.use(http.get(`${API_BASE}/me`, forbidden));
      const err = await getMe().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(403);
    });

    it("raises ApiClientError with status 429 on rate limit", async () => {
      process.env.NEXT_PUBLIC_PROFILE_ME_URL = "/me";
      server.use(http.get(`${API_BASE}/me`, rateLimited));
      const err = await getMe().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(429);
    });
  });

  describe("PATCH /me", () => {
    it("throws ProfileEndpointUnavailableError when env var is unset", async () => {
      const err = await updateMe({ name: "New Name" }).catch((e) => e);
      expect(isProfileEndpointUnavailableError(err)).toBe(true);
    });

    it("returns updated profile on 200", async () => {
      process.env.NEXT_PUBLIC_PROFILE_ME_URL = "/me";
      server.use(
        http.patch(`${API_BASE}/me`, () =>
          HttpResponse.json({ ...mockUserProfile, name: "New Name" }),
        ),
      );
      const profile = await updateMe({ name: "New Name" });
      expect(profile.name).toBe("New Name");
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_PROFILE_ME_URL = "/me";
      server.use(http.patch(`${API_BASE}/me`, notImplemented));
      const err = await updateMe({ name: "x" }).catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /me/preferences", () => {
    it("throws ProfileEndpointUnavailableError when env var is unset", async () => {
      const err = await getMyPreferences().catch((e) => e);
      expect(isProfileEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("preferencesEnabled");
    });

    it("returns normalized preferences on 200", async () => {
      process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL = "/me/preferences";
      server.use(
        http.get(`${API_BASE}/me/preferences`, () =>
          HttpResponse.json(mockUserPreferences),
        ),
      );
      const prefs = await getMyPreferences();
      expect(prefs.theme).toBe("light");
      expect(prefs.language).toBe("en");
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL = "/me/preferences";
      server.use(http.get(`${API_BASE}/me/preferences`, notImplemented));
      const err = await getMyPreferences().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("PATCH /me/preferences", () => {
    it("throws ProfileEndpointUnavailableError when env var is unset", async () => {
      const err = await updateMyPreferences({ theme: "dark" }).catch((e) => e);
      expect(isProfileEndpointUnavailableError(err)).toBe(true);
    });

    it("returns updated preferences on 200", async () => {
      process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL = "/me/preferences";
      server.use(
        http.patch(`${API_BASE}/me/preferences`, () =>
          HttpResponse.json({ ...mockUserPreferences, theme: "dark" }),
        ),
      );
      const prefs = await updateMyPreferences({ theme: "dark" });
      expect(prefs.theme).toBe("dark");
    });
  });
});

// ── Security contracts ─────────────────────────────────────────────────────────

describe("Security API contracts", () => {
  describe("GET /security/sessions", () => {
    it("throws SecurityEndpointUnavailableError when env var is unset", async () => {
      const err = await getSessions().catch((e) => e);
      expect(isSecurityEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("sessionsEnabled");
    });

    it("returns sessions list on 200 (array wrapped in items)", async () => {
      process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL = "/security/sessions";
      server.use(
        http.get(`${API_BASE}/security/sessions`, () =>
          HttpResponse.json({ items: mockSecuritySessions }),
        ),
      );
      const sessions = await getSessions();
      expect(sessions).toHaveLength(2);
      expect(sessions[0].device).toBe("Chrome on macOS");
      expect(sessions[0].is_current).toBe(true);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL = "/security/sessions";
      server.use(http.get(`${API_BASE}/security/sessions`, notImplemented));
      const err = await getSessions().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /security/login-policy", () => {
    it("throws SecurityEndpointUnavailableError when env var is unset", async () => {
      const err = await getLoginPolicy().catch((e) => e);
      expect(isSecurityEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("loginPolicyEnabled");
    });

    it("returns login policy on 200", async () => {
      process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL = "/security/login-policy";
      server.use(
        http.get(`${API_BASE}/security/login-policy`, () =>
          HttpResponse.json(mockLoginPolicy),
        ),
      );
      const policy = await getLoginPolicy();
      expect(policy.invite_only).toBe(true);
      expect(policy.sso_required).toBe(false);
      expect(policy.domain_allowlist).toEqual(["example.com"]);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL = "/security/login-policy";
      server.use(http.get(`${API_BASE}/security/login-policy`, notImplemented));
      const err = await getLoginPolicy().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });

    it("raises ApiClientError with status 403 when non-admin requests login policy", async () => {
      process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL = "/security/login-policy";
      server.use(http.get(`${API_BASE}/security/login-policy`, forbidden));
      const err = await getLoginPolicy().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(403);
    });
  });

  describe("GET /security/posture", () => {
    it("throws SecurityEndpointUnavailableError when env var is unset", async () => {
      const err = await getSecurityPosture().catch((e) => e);
      expect(isSecurityEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("postureEnabled");
    });

    it("returns security posture on 200", async () => {
      process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL = "/security/posture";
      server.use(
        http.get(`${API_BASE}/security/posture`, () =>
          HttpResponse.json(mockSecurityPosture),
        ),
      );
      const posture = await getSecurityPosture();
      expect(posture.prompt_injection_protection).toBe(true);
      expect(posture.tenant_isolation).toBe(true);
      expect(posture.output_validation).toBe(false);
      expect(posture.tool_policy_enforced).toBeNull();
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL = "/security/posture";
      server.use(http.get(`${API_BASE}/security/posture`, notImplemented));
      const err = await getSecurityPosture().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /security/audit-events", () => {
    it("throws SecurityEndpointUnavailableError when env var is unset", async () => {
      const err = await getRecentAuditEvents().catch((e) => e);
      expect(isSecurityEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("auditEnabled");
    });

    it("returns audit events on 200 (items wrapper)", async () => {
      process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL = "/security/audit-events";
      server.use(
        http.get(`${API_BASE}/security/audit-events`, () =>
          HttpResponse.json({ items: mockSecurityAuditEvents }),
        ),
      );
      const events = await getRecentAuditEvents();
      expect(events).toHaveLength(2);
      expect(events[0].event_type).toBe("team.member.invited");
      expect(events[0].actor_email).toBe("alice@example.com");
    });

    it("raises ApiClientError with status 403 when non-admin requests audit events", async () => {
      process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL = "/security/audit-events";
      server.use(http.get(`${API_BASE}/security/audit-events`, forbidden));
      const err = await getRecentAuditEvents().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(403);
    });

    it("raises ApiClientError with status 429 on rate limit", async () => {
      process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL = "/security/audit-events";
      server.use(http.get(`${API_BASE}/security/audit-events`, rateLimited));
      const err = await getRecentAuditEvents().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(429);
    });
  });
});

// ── Organization contracts ─────────────────────────────────────────────────────

describe("Organization API contracts", () => {
  describe("GET /organization", () => {
    it("throws OrganizationEndpointUnavailableError when env var is unset", async () => {
      const err = await getOrganizationProfile().catch((e) => e);
      expect(isOrganizationEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("profileEnabled");
    });

    it("returns organization profile on 200", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_PROFILE_URL = "/organization";
      server.use(
        http.get(`${API_BASE}/organization`, () =>
          HttpResponse.json(mockOrganizationProfile),
        ),
      );
      const profile = await getOrganizationProfile();
      expect(profile.name).toBe("Example Corp");
      expect(profile.slug).toBe("example-corp");
      expect(profile.plan).toBe("Team");
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_PROFILE_URL = "/organization";
      server.use(http.get(`${API_BASE}/organization`, notImplemented));
      const err = await getOrganizationProfile().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /organization/settings", () => {
    it("throws OrganizationEndpointUnavailableError when env var is unset", async () => {
      const err = await getOrganizationSettings().catch((e) => e);
      expect(isOrganizationEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("settingsEnabled");
    });

    it("returns organization settings on 200", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_SETTINGS_URL = "/organization/settings";
      server.use(
        http.get(`${API_BASE}/organization/settings`, () =>
          HttpResponse.json(mockOrganizationSettings),
        ),
      );
      const settings = await getOrganizationSettings();
      expect(settings.default_member_role).toBe("member");
      expect(settings.invite_only).toBe(true);
      expect(settings.evaluation_access).toBe(true);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_SETTINGS_URL = "/organization/settings";
      server.use(
        http.get(`${API_BASE}/organization/settings`, notImplemented),
      );
      const err = await getOrganizationSettings().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });

    it("raises ApiClientError with status 403 when non-admin requests org settings", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_SETTINGS_URL = "/organization/settings";
      server.use(http.get(`${API_BASE}/organization/settings`, forbidden));
      const err = await getOrganizationSettings().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(403);
    });
  });

  describe("GET /organization/ingestion", () => {
    it("throws OrganizationEndpointUnavailableError when env var is unset", async () => {
      const err = await getIngestionDefaults().catch((e) => e);
      expect(isOrganizationEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("ingestionEnabled");
    });

    it("returns ingestion defaults on 200", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_INGESTION_URL = "/organization/ingestion";
      server.use(
        http.get(`${API_BASE}/organization/ingestion`, () =>
          HttpResponse.json(mockIngestionDefaults),
        ),
      );
      const defaults = await getIngestionDefaults();
      expect(defaults.duplicate_handling).toBe("skip");
      expect(defaults.auto_index).toBe(true);
      expect(defaults.allowed_file_types).toContain("pdf");
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_ORGANIZATION_INGESTION_URL = "/organization/ingestion";
      server.use(
        http.get(`${API_BASE}/organization/ingestion`, notImplemented),
      );
      const err = await getIngestionDefaults().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });
});

// ── Billing contracts ──────────────────────────────────────────────────────────

describe("Billing API contracts", () => {
  describe("GET /billing/plan", () => {
    it("throws BillingEndpointUnavailableError when env var is unset", async () => {
      const err = await getBillingPlanInfo().catch((e) => e);
      expect(isBillingEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("planEnabled");
    });

    it("returns plan info on 200", async () => {
      process.env.NEXT_PUBLIC_BILLING_PLAN_URL = "/billing/plan";
      server.use(
        http.get(`${API_BASE}/billing/plan`, () =>
          HttpResponse.json(mockBillingPlanInfo),
        ),
      );
      const plan = await getBillingPlanInfo();
      expect(plan.plan_name).toBe("Team");
      expect(plan.status).toBe("active");
      expect(plan.seats_used).toBe(4);
      expect(plan.can_manage_subscription).toBe(true);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_BILLING_PLAN_URL = "/billing/plan";
      server.use(http.get(`${API_BASE}/billing/plan`, notImplemented));
      const err = await getBillingPlanInfo().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });

    it("raises ApiClientError with status 403 when non-owner requests billing", async () => {
      process.env.NEXT_PUBLIC_BILLING_PLAN_URL = "/billing/plan";
      server.use(http.get(`${API_BASE}/billing/plan`, forbidden));
      const err = await getBillingPlanInfo().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(403);
    });
  });

  describe("GET /billing/usage", () => {
    it("throws BillingEndpointUnavailableError when env var is unset", async () => {
      const err = await getBillingUsageSummary().catch((e) => e);
      expect(isBillingEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("usageEnabled");
    });

    it("returns usage summary on 200", async () => {
      process.env.NEXT_PUBLIC_BILLING_USAGE_URL = "/billing/usage";
      server.use(
        http.get(`${API_BASE}/billing/usage`, () =>
          HttpResponse.json(mockBillingUsageSummary),
        ),
      );
      const usage = await getBillingUsageSummary();
      expect(usage.questions_asked).toBe(820);
      expect(usage.storage_used_gb).toBe(1.2);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_BILLING_USAGE_URL = "/billing/usage";
      server.use(http.get(`${API_BASE}/billing/usage`, notImplemented));
      const err = await getBillingUsageSummary().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /billing/quotas", () => {
    it("throws BillingEndpointUnavailableError when env var is unset", async () => {
      const err = await getBillingQuotas().catch((e) => e);
      expect(isBillingEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("quotasEnabled");
    });

    it("returns quota list on 200", async () => {
      process.env.NEXT_PUBLIC_BILLING_QUOTAS_URL = "/billing/quotas";
      server.use(
        http.get(`${API_BASE}/billing/quotas`, () =>
          HttpResponse.json(mockBillingQuotas),
        ),
      );
      const quotas = await getBillingQuotas();
      expect(quotas).toHaveLength(4);
      expect(quotas[0].resource).toBe("seats");
      expect(quotas[0].used).toBe(4);
      expect(quotas[0].limit).toBe(10);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_BILLING_QUOTAS_URL = "/billing/quotas";
      server.use(http.get(`${API_BASE}/billing/quotas`, notImplemented));
      const err = await getBillingQuotas().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /billing/invoices", () => {
    it("throws BillingEndpointUnavailableError when env var is unset", async () => {
      const err = await getInvoices().catch((e) => e);
      expect(isBillingEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("invoicesEnabled");
    });

    it("returns invoice list on 200", async () => {
      process.env.NEXT_PUBLIC_BILLING_INVOICES_URL = "/billing/invoices";
      server.use(
        http.get(`${API_BASE}/billing/invoices`, () =>
          HttpResponse.json(mockInvoices),
        ),
      );
      const invoices = await getInvoices();
      expect(invoices).toHaveLength(2);
      expect(invoices[0].status).toBe("paid");
      expect(invoices[0].amount_usd).toBe(49.0);
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_BILLING_INVOICES_URL = "/billing/invoices";
      server.use(http.get(`${API_BASE}/billing/invoices`, notImplemented));
      const err = await getInvoices().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });
  });

  describe("GET /billing/contact", () => {
    it("throws BillingEndpointUnavailableError when env var is unset", async () => {
      const err = await getBillingContact().catch((e) => e);
      expect(isBillingEndpointUnavailableError(err)).toBe(true);
      expect(err.endpointKey).toBe("billingContactEnabled");
    });

    it("returns billing contact on 200 (never exposes raw payment data)", async () => {
      process.env.NEXT_PUBLIC_BILLING_CONTACT_URL = "/billing/contact";
      server.use(
        http.get(`${API_BASE}/billing/contact`, () =>
          HttpResponse.json(mockBillingContact),
        ),
      );
      const contact = await getBillingContact();
      expect(contact.email).toBe("billing@example.com");
      expect(contact.payment_method_summary).toBe("Visa ending 4242");
    });

    it("raises ApiClientError with status 501 when backend stub returns NOT_IMPLEMENTED", async () => {
      process.env.NEXT_PUBLIC_BILLING_CONTACT_URL = "/billing/contact";
      server.use(http.get(`${API_BASE}/billing/contact`, notImplemented));
      const err = await getBillingContact().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(501);
    });

    it("raises ApiClientError with status 429 on rate limit", async () => {
      process.env.NEXT_PUBLIC_BILLING_CONTACT_URL = "/billing/contact";
      server.use(http.get(`${API_BASE}/billing/contact`, rateLimited));
      const err = await getBillingContact().catch((e) => e);
      expect(isApiClientError(err)).toBe(true);
      expect(err.status).toBe(429);
    });
  });
});
