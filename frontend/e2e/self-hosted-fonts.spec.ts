import { expect, test } from "@playwright/test";

// R07-04: icons and fonts are served from our own origin.

const SESSION = {
  userId: "e2e-fonts-1",
  email: "member@example.com",
  role: "member",
  organizationId: "c8ae2f17-c58e-499e-88bf-e6b0a8648c21",
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-fonts-token",
  refreshToken: "e2e-fonts-refresh",
};

for (const path of ["/en", "/dashboard"]) {
  test(`${path} makes no third-party font request`, async ({ page }) => {
    const thirdParty: string[] = [];
    page.on("request", (request) => {
      const host = new URL(request.url()).hostname;
      if (host === "fonts.googleapis.com" || host === "fonts.gstatic.com") {
        thirdParty.push(request.url());
      }
    });
    if (path === "/dashboard") {
      await page.addInitScript(
        `window.localStorage.setItem("rudix.session.v1", JSON.stringify(${JSON.stringify(SESSION)}));`,
      );
    }

    const iconFont = page.waitForResponse(
      (response) =>
        response
          .url()
          .endsWith(
            "/fonts/material-symbols/material-symbols-outlined.woff2",
          ) && response.status() === 200,
      { timeout: 30_000 },
    );
    await page.goto(path);
    await iconFont;
    await page.waitForLoadState("networkidle");

    expect(thirdParty).toEqual([]);
  });
}
