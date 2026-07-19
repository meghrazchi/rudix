import { describe, expect, it } from "vitest";

import {
  userProfileSchema,
  updateProfileFormSchema,
  userPreferencesSchema,
  orgProfileFormSchema,
  orgSettingsFormSchema,
  ingestionDefaultsFormSchema,
  loginPolicyFormSchema,
  billingContactFormSchema,
  inviteTeamMemberFormSchema,
  updateTeamMemberRoleFormSchema,
  toSettingsErrorState,
  LANGUAGE_OPTIONS,
} from "@/lib/schemas/settings";

describe("dashboard display languages", () => {
  it("offers Arabic as a profile preference", () => {
    expect(LANGUAGE_OPTIONS).toContainEqual({
      value: "ar",
      label: "العربية",
    });
  });

  it("offers Persian as a profile preference", () => {
    expect(LANGUAGE_OPTIONS).toContainEqual({ value: "fa", label: "فارسی" });
  });
});
import { ApiClientError } from "@/lib/api/errors";

// ── userProfileSchema ─────────────────────────────────────────────────────────

describe("userProfileSchema", () => {
  it("accepts a valid profile with all fields", () => {
    const result = userProfileSchema.safeParse({
      id: "user-1",
      email: "alice@example.com",
      name: "Alice",
      avatarUrl: "https://cdn.example.com/alice.png",
      createdAt: "2026-01-01T00:00:00Z",
    });
    expect(result.success).toBe(true);
  });

  it("accepts a profile with nullable optional fields absent", () => {
    const result = userProfileSchema.safeParse({
      id: "user-1",
      email: "alice@example.com",
      name: "Alice",
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid email", () => {
    const result = userProfileSchema.safeParse({
      id: "user-1",
      email: "not-an-email",
      name: "Alice",
    });
    expect(result.success).toBe(false);
  });
});

// ── updateProfileFormSchema ───────────────────────────────────────────────────

describe("updateProfileFormSchema", () => {
  it("accepts valid name", () => {
    expect(updateProfileFormSchema.safeParse({ name: "Bob" }).success).toBe(
      true,
    );
  });

  it("rejects empty name", () => {
    expect(updateProfileFormSchema.safeParse({ name: "  " }).success).toBe(
      false,
    );
  });

  it("rejects name exceeding 200 characters", () => {
    expect(
      updateProfileFormSchema.safeParse({ name: "a".repeat(201) }).success,
    ).toBe(false);
  });
});

// ── userPreferencesSchema ─────────────────────────────────────────────────────

describe("userPreferencesSchema", () => {
  it("accepts a valid fully-specified preferences object", () => {
    const result = userPreferencesSchema.safeParse({
      language: "en",
      timezone: "America/New_York",
      dateFormat: "YYYY-MM-DD",
      theme: "dark",
      landingPage: "/dashboard",
      keyboardShortcutHints: true,
      emailNotifications: false,
      digestFrequency: "weekly",
    });
    expect(result.success).toBe(true);
  });

  it("accepts an empty object (all fields optional)", () => {
    expect(userPreferencesSchema.safeParse({}).success).toBe(true);
  });

  it("rejects invalid theme value", () => {
    const result = userPreferencesSchema.safeParse({ theme: "neon" });
    expect(result.success).toBe(false);
  });

  it("rejects invalid digestFrequency value", () => {
    const result = userPreferencesSchema.safeParse({
      digestFrequency: "hourly",
    });
    expect(result.success).toBe(false);
  });
});

// ── orgProfileFormSchema ──────────────────────────────────────────────────────

describe("orgProfileFormSchema", () => {
  it("accepts a valid org profile update", () => {
    const result = orgProfileFormSchema.safeParse({
      name: "Acme Corp",
      slug: "acme-corp",
      support_email: "support@acme.com",
      description: "Enterprise AI platform",
    });
    expect(result.success).toBe(true);
  });

  it("rejects empty name", () => {
    expect(orgProfileFormSchema.safeParse({ name: "" }).success).toBe(false);
  });

  it("rejects invalid slug format", () => {
    const result = orgProfileFormSchema.safeParse({
      name: "Acme",
      slug: "UPPERCASE",
    });
    expect(result.success).toBe(false);
  });

  it("rejects invalid support_email", () => {
    const result = orgProfileFormSchema.safeParse({
      name: "Acme",
      support_email: "not-an-email",
    });
    expect(result.success).toBe(false);
  });

  it("coerces empty support_email string to null", () => {
    const result = orgProfileFormSchema.safeParse({
      name: "Acme",
      support_email: "",
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.support_email).toBeNull();
    }
  });
});

// ── orgSettingsFormSchema ─────────────────────────────────────────────────────

describe("orgSettingsFormSchema", () => {
  const valid = {
    default_member_role: "member" as const,
    invite_only: false,
    allowed_email_domains: [],
    default_document_visibility: "private" as const,
    source_download: "admins" as const,
    evaluation_access: false,
    agentic_access: false,
    mcp_access: false,
  };

  it("accepts a valid settings payload", () => {
    expect(orgSettingsFormSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects unknown default_member_role value", () => {
    const result = orgSettingsFormSchema.safeParse({
      ...valid,
      default_member_role: "superadmin",
    });
    expect(result.success).toBe(false);
  });

  it("rejects unknown source_download value", () => {
    const result = orgSettingsFormSchema.safeParse({
      ...valid,
      source_download: "owners_only",
    });
    expect(result.success).toBe(false);
  });
});

// ── ingestionDefaultsFormSchema ───────────────────────────────────────────────

describe("ingestionDefaultsFormSchema", () => {
  const valid = {
    allowed_file_types: ["pdf", "docx"],
    duplicate_handling: "skip" as const,
    auto_index: true,
    reindex_policy: "on_update" as const,
    retry_policy: "once" as const,
    default_metadata_tags: [],
  };

  it("accepts a valid ingestion defaults payload", () => {
    expect(ingestionDefaultsFormSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects invalid duplicate_handling value", () => {
    const result = ingestionDefaultsFormSchema.safeParse({
      ...valid,
      duplicate_handling: "ignore",
    });
    expect(result.success).toBe(false);
  });

  it("rejects non-positive max_upload_size_mb", () => {
    const result = ingestionDefaultsFormSchema.safeParse({
      ...valid,
      max_upload_size_mb: -5,
    });
    expect(result.success).toBe(false);
  });
});

// ── loginPolicyFormSchema ─────────────────────────────────────────────────────

describe("loginPolicyFormSchema", () => {
  it("accepts a valid login policy", () => {
    const result = loginPolicyFormSchema.safeParse({
      domain_allowlist: ["acme.com"],
      session_timeout_hours: 8,
      sso_required: true,
      invite_only: false,
      mfa_required: true,
    });
    expect(result.success).toBe(true);
  });

  it("accepts empty domain_allowlist", () => {
    const result = loginPolicyFormSchema.safeParse({
      domain_allowlist: [],
      sso_required: false,
      invite_only: false,
      mfa_required: false,
    });
    expect(result.success).toBe(true);
  });

  it("rejects non-positive session_timeout_hours", () => {
    const result = loginPolicyFormSchema.safeParse({
      domain_allowlist: [],
      session_timeout_hours: 0,
      sso_required: false,
      invite_only: false,
      mfa_required: false,
    });
    expect(result.success).toBe(false);
  });
});

// ── billingContactFormSchema ──────────────────────────────────────────────────

describe("billingContactFormSchema", () => {
  it("accepts a valid billing contact", () => {
    const result = billingContactFormSchema.safeParse({
      email: "billing@acme.com",
      name: "Acme Finance",
      address_line1: "123 Main St",
      city: "San Francisco",
      state: "CA",
      postal_code: "94105",
      country: "US",
    });
    expect(result.success).toBe(true);
  });

  it("accepts an empty object (all fields optional)", () => {
    expect(billingContactFormSchema.safeParse({}).success).toBe(true);
  });

  it("rejects invalid email", () => {
    const result = billingContactFormSchema.safeParse({
      email: "not-an-email",
    });
    expect(result.success).toBe(false);
  });

  it("coerces empty email string to null", () => {
    const result = billingContactFormSchema.safeParse({ email: "" });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.email).toBeNull();
    }
  });
});

// ── inviteTeamMemberFormSchema ────────────────────────────────────────────────

describe("inviteTeamMemberFormSchema", () => {
  it("accepts valid email and role", () => {
    const result = inviteTeamMemberFormSchema.safeParse({
      email: "bob@example.com",
      role: "member",
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid email", () => {
    const result = inviteTeamMemberFormSchema.safeParse({
      email: "not-valid",
      role: "member",
    });
    expect(result.success).toBe(false);
  });

  it("rejects owner role (not allowed in invite)", () => {
    const result = inviteTeamMemberFormSchema.safeParse({
      email: "owner@example.com",
      role: "owner",
    });
    expect(result.success).toBe(false);
  });

  it("rejects empty email", () => {
    const result = inviteTeamMemberFormSchema.safeParse({
      email: "",
      role: "admin",
    });
    expect(result.success).toBe(false);
  });
});

// ── updateTeamMemberRoleFormSchema ────────────────────────────────────────────

describe("updateTeamMemberRoleFormSchema", () => {
  it("accepts valid roles", () => {
    for (const role of ["admin", "member", "viewer"] as const) {
      expect(updateTeamMemberRoleFormSchema.safeParse({ role }).success).toBe(
        true,
      );
    }
  });

  it("rejects owner role", () => {
    expect(
      updateTeamMemberRoleFormSchema.safeParse({ role: "owner" }).success,
    ).toBe(false);
  });
});

// ── toSettingsErrorState ──────────────────────────────────────────────────────

describe("toSettingsErrorState", () => {
  it("returns none for null", () => {
    expect(toSettingsErrorState(null)).toEqual({ kind: "none" });
  });

  it("returns forbidden for 403 ApiClientError", () => {
    const error = new ApiClientError({
      status: 403,
      code: "forbidden",
      message: "Forbidden",
      details: null,
      requestId: null,
      userMessage: "You do not have permission for this action.",
      actionMessage: null,
      retryable: false,
    });
    expect(toSettingsErrorState(error)).toEqual({ kind: "forbidden" });
  });

  it("returns rate_limited for 429 ApiClientError", () => {
    const error = new ApiClientError({
      status: 429,
      code: "rate_limited",
      message: "Rate limited",
      details: null,
      requestId: null,
      userMessage: "Too many requests were sent.",
      actionMessage: "Wait a moment, then retry.",
      retryable: true,
    });
    expect(toSettingsErrorState(error)).toEqual({ kind: "rate_limited" });
  });

  it("returns error with userMessage for other ApiClientError statuses", () => {
    const error = new ApiClientError({
      status: 500,
      code: "unknown_error",
      message: "Internal server error",
      details: null,
      requestId: null,
      userMessage: "Something went wrong while contacting the API.",
      actionMessage: "Try again.",
      retryable: false,
    });
    const state = toSettingsErrorState(error);
    expect(state.kind).toBe("error");
    if (state.kind === "error") {
      expect(state.message).toBe(
        "Something went wrong while contacting the API.",
      );
    }
  });

  it("returns unavailable for endpoint unavailable errors", () => {
    const unavailableErrors = [
      { name: "OrganizationEndpointUnavailableError" },
      { name: "BillingEndpointUnavailableError" },
      { name: "TeamEndpointUnavailableError" },
      { name: "SecurityEndpointUnavailableError" },
      { name: "ProfileEndpointUnavailableError" },
    ];
    for (const err of unavailableErrors) {
      expect(toSettingsErrorState(err)).toEqual({ kind: "unavailable" });
    }
  });

  it("returns generic error for unknown error types", () => {
    const state = toSettingsErrorState(new Error("unexpected"));
    expect(state.kind).toBe("error");
  });
});
