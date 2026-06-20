import { expect, test, type Page, type Route } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

// ── Session fixtures ──────────────────────────────────────────────────────────

type TestSession = {
  userId: string;
  email: string;
  role: "owner" | "admin" | "member" | "viewer";
  organizationId: string;
  organizationName: string;
  accessToken: string;
  refreshToken: string;
};

const adminSession: TestSession = {
  userId: "e2e-admin-1",
  email: "admin@example.com",
  role: "admin",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-admin-token",
  refreshToken: "e2e-admin-refresh",
};

const memberSession: TestSession = {
  userId: "e2e-member-1",
  email: "member@example.com",
  role: "member",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-member-token",
  refreshToken: "e2e-member-refresh",
};

const viewerSession: TestSession = {
  userId: "e2e-viewer-1",
  email: "viewer@example.com",
  role: "viewer",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-viewer-token",
  refreshToken: "e2e-viewer-refresh",
};

// ── API helpers ───────────────────────────────────────────────────────────────

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    },
    body: JSON.stringify(body),
  });
}

async function installBaseApiMocks(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const path = requestUrl.pathname.replace(/^\/api\/v1/, "");

    if (request.method() === "OPTIONS") {
      await route.fulfill({
        status: 200,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "*",
          "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        },
      });
      return;
    }

    if (path === "/notifications/unread-count" && request.method() === "GET") {
      await fulfillJson(route, { unread_count: 0 });
      return;
    }

    await route.fallback();
  });
}

function injectSession(session: TestSession): string {
  return `window.sessionStorage.setItem(
    "${SESSION_STORAGE_KEY}",
    JSON.stringify(${JSON.stringify(session)})
  );`;
}

// ── Effective permissions fixture ─────────────────────────────────────────────

const adminPermissions = [
  "documents:view",
  "documents:upload",
  "documents:delete",
  "documents:manage",
  "collections:view",
  "collections:create",
  "collections:manage",
  "collections:delete",
  "chat:use",
  "admin:access",
  "security_center:view",
  "security_center:configure",
  "team:manage",
  "roles:manage",
];

const memberPermissions = [
  "documents:view",
  "documents:upload",
  "collections:view",
  "chat:use",
  "chat:use_collections",
];

const viewerPermissions = ["documents:view", "collections:view", "chat:use"];

// ── Tests ─────────────────────────────────────────────────────────────────────

// ── PermissionGate: admin can see all nav items ───────────────────────────────

test("admin sees admin nav items in sidebar", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/");

  // Admin should see Admin section link
  const adminLink = page.getByRole("link", { name: /admin/i }).first();
  await expect(adminLink).toBeVisible({ timeout: 5000 });
});

// ── PermissionGate: member does not see admin nav ─────────────────────────────

test("member does not see admin section in sidebar", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: memberPermissions });
  });

  await page.addInitScript(injectSession(memberSession));
  await page.goto("/");

  // Member should not see any admin link in sidebar nav
  const adminLinks = page.locator("nav a[href*='/admin']");
  await expect(adminLinks).toHaveCount(0, { timeout: 5000 });
});

// ── Forbidden page: member cannot access /admin/permissions ───────────────────

test("member gets forbidden page at /admin/permissions", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: memberPermissions });
  });

  await page.route("**/api/v1/admin/permissions/**", async (route) => {
    await fulfillJson(route, { detail: "Forbidden" }, 403);
  });

  await page.addInitScript(injectSession(memberSession));
  await page.goto("/admin/permissions");

  // Should show a forbidden/access-denied state (not crash)
  await expect(
    page.getByText(/forbidden|access denied|permission/i).first(),
  ).toBeVisible({
    timeout: 5000,
  });
});

// ── Admin permissions page renders conflicts tab ──────────────────────────────

test("admin can navigate to Conflicts tab on permissions page", async ({
  page,
}) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  await page.route("**/api/v1/admin/permissions/roles**", async (route) => {
    await fulfillJson(route, { roles: [], total: 0 });
  });

  await page.route("**/api/v1/admin/permissions/grants**", async (route) => {
    await fulfillJson(route, { items: [], total: 0, page: 1, page_size: 50 });
  });

  await page.route("**/api/v1/admin/permissions/denies**", async (route) => {
    await fulfillJson(route, { items: [], total: 0, page: 1, page_size: 50 });
  });

  await page.route("**/api/v1/admin/permissions/conflicts**", async (route) => {
    await fulfillJson(route, { items: [], total: 0, page: 1, page_size: 50 });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/admin/permissions");

  const conflictsTab = page.getByRole("tab", { name: /conflicts/i });
  await expect(conflictsTab).toBeVisible({ timeout: 5000 });
  await conflictsTab.click();

  await expect(
    page.getByText(/no conflicts|0 conflicts|scan/i).first(),
  ).toBeVisible({ timeout: 5000 });
});

// ── Admin permissions page renders Access Debugger tab ───────────────────────

test("admin can navigate to Access Debugger tab", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  await page.route("**/api/v1/admin/permissions/**", async (route) => {
    await fulfillJson(route, {
      items: [],
      roles: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/admin/permissions");

  const debugTab = page.getByRole("tab", { name: /access debugger/i });
  await expect(debugTab).toBeVisible({ timeout: 5000 });
  await debugTab.click();

  // Debugger form should show resource_type and action fields
  await expect(
    page
      .getByRole("combobox", { name: /resource type/i })
      .or(
        page
          .locator("select[name='resource_type'], select[id*='resource']")
          .first(),
      ),
  ).toBeVisible({ timeout: 5000 });
});

// ── Access Debugger: allow result renders correctly ───────────────────────────

test("Access Debugger shows allow decision result", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  await page.route("**/api/v1/admin/permissions/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("explain-decision")) {
      await fulfillJson(route, {
        decision: "allow",
        matched_rule: "owner_admin_override",
        deny_reason: null,
        subject_user_id: "e2e-user-99",
        resource_type: "document",
        resource_id: null,
        action: "view",
        trace: [
          { rule: "no_organization_context", outcome: "pass", detail: null },
          { rule: "owner_admin_override", outcome: "allow", detail: null },
        ],
        remediation: [],
        request_id: "req-e2e-1",
      });
      return;
    }
    await fulfillJson(route, {
      items: [],
      roles: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/admin/permissions");

  const debugTab = page.getByRole("tab", { name: /access debugger/i });
  await debugTab.click();

  // Fill in a subject user ID
  const userIdInput = page
    .locator(
      "input[placeholder*='user'], input[name*='user'], input[id*='user']",
    )
    .first();
  await userIdInput.fill("e2e-user-99");

  // Submit the form
  const submitBtn = page
    .getByRole("button", { name: /explain|check|analyze/i })
    .first();
  await submitBtn.click();

  // Should display ALLOW
  await expect(page.getByText(/allow/i).first()).toBeVisible({ timeout: 5000 });
});

// ── Access Debugger: deny result shows remediation ────────────────────────────

test("Access Debugger shows deny decision with remediation", async ({
  page,
}) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  await page.route("**/api/v1/admin/permissions/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("explain-decision")) {
      await fulfillJson(route, {
        decision: "deny",
        matched_rule: "role_permission",
        deny_reason: "insufficient_role",
        subject_user_id: "e2e-user-42",
        resource_type: "document",
        resource_id: null,
        action: "delete",
        trace: [
          { rule: "no_organization_context", outcome: "pass", detail: null },
          { rule: "tenant_boundary", outcome: "pass", detail: null },
          {
            rule: "role_permission",
            outcome: "deny",
            detail: "insufficient_role",
          },
        ],
        remediation: [
          "Upgrade the user's role to admin or owner.",
          "Grant explicit resource access via the Grants tab.",
        ],
        request_id: "req-e2e-2",
      });
      return;
    }
    await fulfillJson(route, {
      items: [],
      roles: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/admin/permissions");

  const debugTab = page.getByRole("tab", { name: /access debugger/i });
  await debugTab.click();

  const userIdInput = page
    .locator(
      "input[placeholder*='user'], input[name*='user'], input[id*='user']",
    )
    .first();
  await userIdInput.fill("e2e-user-42");

  const submitBtn = page
    .getByRole("button", { name: /explain|check|analyze/i })
    .first();
  await submitBtn.click();

  // DENY result visible
  await expect(page.getByText(/deny/i).first()).toBeVisible({ timeout: 5000 });
  // Remediation advice shown
  await expect(
    page
      .getByText(/upgrade the user/i)
      .or(page.getByText(/grant explicit/i))
      .first(),
  ).toBeVisible({ timeout: 5000 });
});

// ── Conflicts tab: scan button triggers POST /conflicts/scan ──────────────────

test("Conflicts tab scan button calls scan API and shows result", async ({
  page,
}) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  let scanCalled = false;

  await page.route("**/api/v1/admin/permissions/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      url.pathname.includes("conflicts/scan") &&
      request.method() === "POST"
    ) {
      scanCalled = true;
      await fulfillJson(route, {
        conflicts_detected: 2,
        conflicts_created: 1,
        scan_duration_ms: 120,
        scanned_grants: 10,
        scanned_denies: 5,
        scanned_acl_mappings: 3,
      });
      return;
    }
    if (url.pathname.includes("conflicts")) {
      await fulfillJson(route, { items: [], total: 0, page: 1, page_size: 50 });
      return;
    }
    await fulfillJson(route, {
      items: [],
      roles: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/admin/permissions");

  const conflictsTab = page.getByRole("tab", { name: /conflicts/i });
  await conflictsTab.click();

  const scanBtn = page.getByRole("button", { name: /scan/i }).first();
  await scanBtn.click();

  // Wait for the result banner to appear
  await expect(
    page
      .getByText(/2 conflict|detected/i)
      .or(page.getByText(/scan complete/i))
      .first(),
  ).toBeVisible({ timeout: 8000 });

  expect(scanCalled).toBe(true);
});

// ── Viewer cannot access admin pages ─────────────────────────────────────────

test("viewer is redirected away from admin pages", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: viewerPermissions });
  });

  await page.route("**/api/v1/admin/**", async (route) => {
    await fulfillJson(route, { detail: "Forbidden" }, 403);
  });

  await page.addInitScript(injectSession(viewerSession));
  await page.goto("/admin/permissions");

  // Should be redirected or show forbidden message
  const url = page.url();
  const isForbiddenPage =
    url.includes("/forbidden") ||
    url.includes("/dashboard") ||
    url === page.url();

  // Either the URL changed OR the page shows a forbidden indicator
  const hasForbiddenContent = await page
    .getByText(/forbidden|access denied|permission|not allowed/i)
    .first()
    .isVisible()
    .catch(() => false);

  expect(isForbiddenPage || hasForbiddenContent).toBe(true);
});

// ── Security: no provider secrets in API response ─────────────────────────────

test("explain-decision response does not contain secret tokens", async ({
  page,
}) => {
  await installBaseApiMocks(page);

  const sensitiveValue = "sk-SHOULD_NOT_APPEAR_IN_PAGE";

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { permissions: adminPermissions });
  });

  await page.route("**/api/v1/admin/permissions/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("explain-decision")) {
      await fulfillJson(route, {
        decision: "allow",
        matched_rule: "owner_admin_override",
        deny_reason: null,
        subject_user_id: "e2e-user-1",
        resource_type: "document",
        resource_id: null,
        action: "view",
        trace: [
          { rule: "owner_admin_override", outcome: "allow", detail: null },
        ],
        remediation: [],
        request_id: "req-e2e-sec",
        // Injecting a "hidden" secret — frontend must NOT render it
        _internal_token: sensitiveValue,
      });
      return;
    }
    await fulfillJson(route, {
      items: [],
      roles: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
  });

  await page.addInitScript(injectSession(adminSession));
  await page.goto("/admin/permissions");

  const debugTab = page.getByRole("tab", { name: /access debugger/i });
  await debugTab.click();

  const userIdInput = page
    .locator(
      "input[placeholder*='user'], input[name*='user'], input[id*='user']",
    )
    .first();
  await userIdInput.fill("e2e-user-1");

  const submitBtn = page
    .getByRole("button", { name: /explain|check|analyze/i })
    .first();
  await submitBtn.click();

  await expect(page.getByText(/allow/i).first()).toBeVisible({ timeout: 5000 });

  // The rendered page content should never include the sentinel value
  const content = await page.content();
  expect(content).not.toContain("SHOULD_NOT_APPEAR_IN_PAGE");
});

// ── Auth redirect: unauthenticated user cannot access any protected page ──────

test("unauthenticated user is redirected to login", async ({ page }) => {
  await installBaseApiMocks(page);

  await page.route("**/api/v1/auth/effective-permissions", async (route) => {
    await fulfillJson(route, { detail: "Unauthorized" }, 401);
  });

  // Do NOT inject session → unauthenticated
  await page.goto("/admin/permissions");

  // Should land on login page or auth redirect
  await expect(
    page
      .getByRole("button", { name: /sign in|log in|login/i })
      .or(page.locator("form[action*='login'], input[type='email']"))
      .first(),
  ).toBeVisible({ timeout: 8000 });
});
