import { describe, expect, it, vi, beforeEach } from "vitest";
import { discoverSSOForEmail } from "@/lib/auth-login";

const mockDiscoverSSO = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/sso", () => ({
  discoverSSO: mockDiscoverSSO,
}));

describe("discoverSSOForEmail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns not_found for empty email", async () => {
    const result = await discoverSSOForEmail("");
    expect(result.status).toBe("not_found");
  });

  it("returns not_found for email without @", async () => {
    const result = await discoverSSOForEmail("noemail");
    expect(result.status).toBe("not_found");
  });

  it("returns not_found when API says sso_enabled=false", async () => {
    mockDiscoverSSO.mockResolvedValue({
      sso_enabled: false,
      sso_type: null,
      redirect_url: null,
      domain: "unknown.com",
    });
    const result = await discoverSSOForEmail("user@unknown.com");
    expect(result.status).toBe("not_found");
  });

  it("returns found with redirect_url when SSO is enabled", async () => {
    mockDiscoverSSO.mockResolvedValue({
      sso_enabled: true,
      sso_type: "saml",
      redirect_url: "https://api.example.com/auth/sso/org-1/initiate",
      domain: "corp.com",
    });
    const result = await discoverSSOForEmail("alice@corp.com");
    expect(result.status).toBe("found");
    if (result.status === "found") {
      expect(result.redirectUrl).toBe(
        "https://api.example.com/auth/sso/org-1/initiate",
      );
      expect(result.domain).toBe("corp.com");
      expect(result.ssoType).toBe("saml");
    }
  });

  it("normalizes email to lowercase before discovery", async () => {
    mockDiscoverSSO.mockResolvedValue({
      sso_enabled: false,
      sso_type: null,
      redirect_url: null,
      domain: "corp.com",
    });
    await discoverSSOForEmail("Alice@CORP.COM");
    expect(mockDiscoverSSO).toHaveBeenCalledWith("alice@corp.com");
  });

  it("returns error when API throws", async () => {
    mockDiscoverSSO.mockRejectedValue(new Error("network error"));
    const result = await discoverSSOForEmail("user@error.com");
    expect(result.status).toBe("error");
  });

  it("returns not_found when sso_enabled=true but redirect_url is null", async () => {
    mockDiscoverSSO.mockResolvedValue({
      sso_enabled: true,
      sso_type: "saml",
      redirect_url: null,
      domain: "partial.com",
    });
    const result = await discoverSSOForEmail("user@partial.com");
    expect(result.status).toBe("not_found");
  });
});
