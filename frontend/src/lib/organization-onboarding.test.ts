import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  completeOrganizationOnboarding,
  loadOrganizationOnboardingDraft,
  organizationOnboardingSchema,
  parseDomainAllowlist,
  persistOrganizationOnboardingDraft,
  type OrganizationOnboardingFormValues,
} from "@/lib/organization-onboarding";

const VALID_VALUES: OrganizationOnboardingFormValues = {
  workspaceName: "Acme Workspace",
  domainAllowlistText: "acme.com\nExample.org",
  defaultAccessRole: "member",
  allowSelfServeJoin: true,
  invites: [
    { email: "owner@acme.com", role: "admin" },
    { email: "", role: "member" },
  ],
};

describe("organization onboarding helpers", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_RESUME_URL;
    delete process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_SAVE_URL;
    delete process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_COMPLETE_URL;
    process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_LOCAL_FALLBACK = "true";
    window.localStorage.clear();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    window.localStorage.clear();
  });

  it("parses and deduplicates allowlist domains", () => {
    expect(parseDomainAllowlist(" Acme.com,example.org\nacme.com \n")).toEqual([
      "acme.com",
      "example.org",
    ]);
  });

  it("validates invalid allowlist domains and duplicate invites", () => {
    const result = organizationOnboardingSchema.safeParse({
      ...VALID_VALUES,
      domainAllowlistText: "acme.com,invalid_domain",
      invites: [
        { email: "owner@acme.com", role: "admin" },
        { email: "owner@acme.com", role: "member" },
      ],
    });

    expect(result.success).toBe(false);

    if (!result.success) {
      const messages = result.error.issues.map((issue) => issue.message);
      expect(messages).toContain("Invalid domain in allowlist: invalid_domain");
      expect(messages).toContain("Duplicate invite email");
    }
  });

  it("persists and reloads onboarding draft without backend endpoints", async () => {
    await persistOrganizationOnboardingDraft(VALID_VALUES);
    const loaded = await loadOrganizationOnboardingDraft();

    expect(loaded).toEqual({
      workspaceName: "Acme Workspace",
      domainAllowlistText: "acme.com\nexample.org",
      defaultAccessRole: "member",
      allowSelfServeJoin: true,
      invites: [{ email: "owner@acme.com", role: "admin" }],
    });
  });

  it("completes onboarding using local fallback and clears draft", async () => {
    await persistOrganizationOnboardingDraft(VALID_VALUES);

    const result = await completeOrganizationOnboarding(VALID_VALUES);
    const loadedAfterComplete = await loadOrganizationOnboardingDraft();

    expect(result).toEqual({
      organizationId: "org-acme-workspace",
      organizationName: "Acme Workspace",
      role: "admin",
    });
    expect(loadedAfterComplete).toBeNull();
  });

  it("fails safely when completion endpoint and local fallback are both unavailable", async () => {
    process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_LOCAL_FALLBACK = "false";
    (process.env as Record<string, string | undefined>).NODE_ENV = "production";

    await expect(completeOrganizationOnboarding(VALID_VALUES)).rejects.toMatchObject({
      kind: "not_configured",
      safeMessage: "Organization onboarding is not configured for this environment.",
    });
  });
});
