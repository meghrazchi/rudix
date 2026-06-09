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
  userId: "e2e-user-1",
  email: "admin@example.com",
  role: "admin",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
};

const memberSession: TestSession = {
  userId: "e2e-user-2",
  email: "member@example.com",
  role: "member",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
};

// ── API mock helpers ──────────────────────────────────────────────────────────

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

async function installApiMocks(page: Page): Promise<void> {
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

    if (path === "/auth/login" && request.method() === "POST") {
      await fulfillJson(route, {
        access_token: "login-token",
        refresh_token: "login-refresh",
        user_id: "e2e-user-1",
        email: "admin@example.com",
        role: "admin",
        organization_id: ORG_ID,
        organization_name: "Rudix E2E Org",
      });
      return;
    }

    if (
      path === "/admin/chunking-profiles/strategies" &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, {
        strategies: [
          {
            name: "adaptive_hybrid",
            display_name: "Adaptive Hybrid",
            description:
              "Selects a concrete chunking strategy based on structure and OCR signals.",
            suitable_for: ["mixed enterprise content", "production defaults"],
            requires_page_structure: false,
            supports_hierarchical: false,
          },
        ],
        default_config: {
          strategy: "adaptive_hybrid",
          chunk_size_tokens: 700,
          chunk_overlap_tokens: 120,
          language: null,
          min_tokens: 88,
          strategy_options: {},
        },
        feature_chunking_profiles_enabled: true,
      });
      return;
    }

    if (path === "/admin/chunking-profiles" && request.method() === "GET") {
      await fulfillJson(route, {
        profiles: [
          {
            profile_id: "profile-1",
            organization_id: ORG_ID,
            name: "Operations Default",
            slug: "operations-default",
            config: {
              strategy: "adaptive_hybrid",
              chunk_size_tokens: 700,
              chunk_overlap_tokens: 120,
              language: "en",
              min_tokens: 88,
              strategy_options: {},
            },
            is_default: true,
            is_system: false,
            created_at: "2026-05-20T08:00:00Z",
            updated_at: "2026-05-20T08:00:00Z",
            created_by_user_id: "e2e-user-1",
            updated_by_user_id: "e2e-user-1",
          },
        ],
        total: 1,
        has_org_default: true,
      });
      return;
    }

    if (path === "/admin/model-providers" && request.method() === "GET") {
      await fulfillJson(route, {
        providers: [
          {
            provider_key: "chat",
            provider_type: "openai",
            model_name: "gpt-4o",
            is_configured: true,
            task_assignments: [
              "chat",
              "summarization",
              "comparison",
              "evaluations",
              "agentic",
            ],
            capability: {
              context_window: 128000,
              supports_json_mode: true,
              supports_tool_calling: true,
              supports_streaming: true,
              is_embedding_model: false,
              embedding_dimension: null,
              cost_behavior: "per_token",
            },
            reindex_required: false,
          },
          {
            provider_key: "embeddings",
            provider_type: "openai",
            model_name: "text-embedding-3-small",
            is_configured: true,
            task_assignments: ["embeddings"],
            capability: {
              context_window: 8191,
              supports_json_mode: false,
              supports_tool_calling: false,
              supports_streaming: false,
              is_embedding_model: true,
              embedding_dimension: 1536,
              cost_behavior: "per_token",
            },
            reindex_required: false,
          },
        ],
      });
      return;
    }

    if (
      path === "/admin/model-providers/test" &&
      request.method() === "POST"
    ) {
      const body = await request.postDataJSON();
      await fulfillJson(route, {
        provider_key: body.provider_key,
        provider_type: "openai",
        model_name: body.provider_key === "chat" ? "gpt-4o" : "text-embedding-3-small",
        status: "ok",
        latency_ms: 87,
        error_code: null,
        error_message: null,
      });
      return;
    }

    await fulfillJson(
      route,
      { detail: `No settings e2e mock for ${request.method()} ${path}` },
      404,
    );
  });
}

async function seedAuthenticatedSession(
  page: Page,
  session: TestSession = adminSession,
): Promise<void> {
  await page.addInitScript(
    ({ storageKey, payload }) => {
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    },
    { storageKey: SESSION_STORAGE_KEY, payload: session },
  );
}

async function waitForSessionBootstrap(page: Page): Promise<void> {
  const loadingHeading = page.getByRole("heading", { name: "Loading session" });
  if (await loadingHeading.isVisible().catch(() => false)) {
    await expect(loadingHeading).toBeHidden({ timeout: 30_000 });
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Settings E2E smoke", () => {
  // ── Auth boundary ───────────────────────────────────────────────────────────

  test("unauthenticated user is redirected to login from /settings", async ({
    page,
  }) => {
    await installApiMocks(page);
    await page.goto("/settings");
    await waitForSessionBootstrap(page);
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });

  // ── Default tab ─────────────────────────────────────────────────────────────

  test("authenticated user lands on Profile tab by default at /settings", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings");
    await waitForSessionBootstrap(page);

    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Profile" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("tabpanel")).toBeVisible();
  });

  // ── Profile tab ─────────────────────────────────────────────────────────────

  test("Profile tab shows account identity from session", async ({ page }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=profile");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Account Identity" }),
    ).toBeVisible();
    await expect(page.getByText("admin@example.com")).toBeVisible();
    // Role badge is rendered with `capitalize` CSS; DOM text is "admin"
    await expect(
      page
        .getByRole("region", { name: "Account identity section" })
        .getByText("admin"),
    ).toBeVisible();
  });

  test("Profile tab save stores preferences locally and shows toast", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=profile");
    await waitForSessionBootstrap(page);

    await page.getByRole("button", { name: "Update Profile" }).click();

    // No save URL in E2E env → local persistence scope
    await expect(
      page.getByText("Preferences saved locally for this browser session."),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("Profile tab Discard Changes button is present and resets the form", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=profile");
    await waitForSessionBootstrap(page);

    // Default theme is "light" — click the Dark theme label to dirty the form
    await page
      .locator("label")
      .filter({ hasText: /^Dark$/i })
      .click();
    await expect(
      page.locator('input[type="radio"][value="dark"]'),
    ).toBeChecked();

    // Discard should revert to the last-saved (light) theme
    await page.getByRole("button", { name: "Discard Changes" }).click();
    await expect(
      page.locator('input[type="radio"][value="light"]'),
    ).toBeChecked();
  });

  // ── Direct tab URLs ─────────────────────────────────────────────────────────

  test("direct URL /settings?tab=profile activates the Profile tab", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=profile");
    await waitForSessionBootstrap(page);

    await expect(page.getByRole("tab", { name: "Profile" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(
      page.getByRole("heading", { name: "Account Identity" }),
    ).toBeVisible();
  });

  test("direct URL /settings?tab=organization activates the Organization tab", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=organization");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("tab", { name: "Organization" }),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByRole("heading", { name: "Organization Profile" }),
    ).toBeVisible();
    // Session org name is always shown regardless of backend availability
    await expect(page.getByText("Rudix E2E Org")).toBeVisible();
  });

  test("direct URL /settings?tab=security activates the Security tab", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=security");
    await waitForSessionBootstrap(page);

    await expect(page.getByRole("tab", { name: "Security" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByText("Authentication & Session")).toBeVisible();
  });

  test("direct URL /settings?tab=billing activates the Billing tab for admin", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=billing");
    await waitForSessionBootstrap(page);

    await expect(page.getByRole("tab", { name: "Billing" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // No billing URL env vars in E2E → deployment-controlled fallback
    await expect(
      page.getByText(/Plan details are not available/),
    ).toBeVisible();
    // Billing Alerts section always renders
    await expect(
      page.getByRole("heading", { name: "Billing Alerts" }),
    ).toBeVisible();
  });

  // ── Security: token redaction ───────────────────────────────────────────────

  test("Security tab shows auth metadata but never renders raw token values", async ({
    page,
  }) => {
    await installApiMocks(page);
    // Session fixture contains accessToken: "e2e-access-token" and refreshToken: "e2e-refresh-token"
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=security");
    await waitForSessionBootstrap(page);

    // Auth metadata labels are shown
    await expect(page.getByText("Access token attached")).toBeVisible();
    await expect(page.getByText("Refresh token available")).toBeVisible();

    // The raw token strings must never appear in the page text
    const bodyText = (await page.textContent("body")) ?? "";
    expect(bodyText).not.toContain("e2e-access-token");
    expect(bodyText).not.toContain("e2e-refresh-token");

    // The explicit disclaimer must be present
    await expect(
      page.getByText("Token values are never displayed."),
    ).toBeVisible();
  });

  // ── Organization: admin controls ────────────────────────────────────────────

  test("admin sees Chunking Profiles section on Organization tab", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=organization");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Chunking Profiles" }),
    ).toBeVisible();
  });

  test("admin sees team management controls on Organization tab", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=organization");
    await waitForSessionBootstrap(page);

    // TeamManagementSection always renders its heading regardless of capabilities
    await expect(
      page.getByRole("heading", { name: "Team management" }),
    ).toBeVisible();
  });

  // ── Permission-aware rendering ──────────────────────────────────────────────

  test("non-admin member is forbidden from the Billing tab", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page, memberSession);

    await page.goto("/settings?tab=billing");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Billing restricted" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Billing settings are available to owners and admins only.",
      ),
    ).toBeVisible();
  });

  test("admin Role & Access Policy shows admin capabilities", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=security");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Role & Access Policy" }),
    ).toBeVisible();
    // "Org settings only" is the admin-controls description for the admin role
    await expect(page.getByText("Org settings only")).toBeVisible();
  });

  test("member Role & Access Policy does not show admin-only capabilities", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page, memberSession);

    await page.goto("/settings?tab=security");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Role & Access Policy" }),
    ).toBeVisible();
    // Admin-only capability description must not appear for a member
    await expect(page.getByText("Org settings only")).not.toBeVisible();
  });

  // ── Tab navigation ──────────────────────────────────────────────────────────

  test("clicking tabs updates the URL and switches the active panel", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings");
    await waitForSessionBootstrap(page);

    // Profile is selected on initial load
    await expect(page.getByRole("tab", { name: "Profile" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // → Organization
    await page.getByRole("tab", { name: "Organization" }).click();
    await expect(page).toHaveURL(/[?&]tab=organization/);
    await expect(
      page.getByRole("tab", { name: "Organization" }),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByRole("heading", { name: "Organization Profile" }),
    ).toBeVisible();

    // → Security
    await page.getByRole("tab", { name: "Security" }).click();
    await expect(page).toHaveURL(/[?&]tab=security/);
    await expect(page.getByRole("tab", { name: "Security" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByText("Authentication & Session")).toBeVisible();

    // → Billing
    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page).toHaveURL(/[?&]tab=billing/);
    await expect(page.getByRole("tab", { name: "Billing" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(
      page.getByRole("heading", { name: "Billing Alerts" }),
    ).toBeVisible();

    // → back to Profile
    await page.getByRole("tab", { name: "Profile" }).click();
    await expect(page).toHaveURL(/[?&]tab=profile/);
    await expect(page.getByRole("tab", { name: "Profile" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(
      page.getByRole("heading", { name: "Account Identity" }),
    ).toBeVisible();
  });
});

// ── Model provider diagnostics smoke ─────────────────────────────────────────

test.describe("Model provider diagnostics E2E smoke", () => {
  test("admin can navigate to /admin/model-diagnostics and see provider cards", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/admin/model-diagnostics");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Model provider diagnostics" }),
    ).toBeVisible();
    await expect(page.getByText("gpt-4o")).toBeVisible();
    await expect(page.getByText("text-embedding-3-small")).toBeVisible();
  });

  test("admin sees both provider cards with Configured badges", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/admin/model-diagnostics");
    await waitForSessionBootstrap(page);

    const configuredBadges = page.getByText("Configured");
    await expect(configuredBadges.first()).toBeVisible();
  });

  test("admin sees Test connection buttons and can click one", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/admin/model-diagnostics");
    await waitForSessionBootstrap(page);

    const testButtons = page.getByRole("button", { name: "Test connection" });
    await expect(testButtons.first()).toBeVisible();

    await testButtons.first().click();

    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("87 ms")).toBeVisible();
  });

  test("non-admin member sees provider cards but no Test connection button", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page, memberSession);

    await page.goto("/admin/model-diagnostics");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Model provider diagnostics" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Test connection" }),
    ).not.toBeVisible();
  });

  test("unauthenticated user is redirected to login from /admin/model-diagnostics", async ({
    page,
  }) => {
    await installApiMocks(page);
    await page.goto("/admin/model-diagnostics");
    await waitForSessionBootstrap(page);
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });
});
