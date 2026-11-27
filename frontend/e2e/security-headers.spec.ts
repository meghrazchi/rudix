import { expect, test } from "@playwright/test";

// Public marketing page, public auth page, and an authenticated app route.
for (const path of ["/en", "/login", "/dashboard"]) {
  test(`security headers are present on ${path}`, async ({ request }) => {
    const response = await request.get(path);
    expect(response.status()).toBeLessThan(400);
    const headers = response.headers();

    const csp = headers["content-security-policy-report-only"];
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("default-src 'self'");
    expect(headers["content-security-policy"]).toBeUndefined();
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["permissions-policy"]).toContain("camera=()");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["strict-transport-security"]).toBeUndefined();
  });
}
