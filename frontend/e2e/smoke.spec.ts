import { expect, test, type Page, type Route } from "@playwright/test";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

type TestSession = {
  userId: string;
  email: string;
  role: "owner" | "admin" | "member" | "viewer";
  organizationId: string;
  organizationName: string;
  accessToken: string;
  refreshToken: string;
};

const baseSession: TestSession = {
  userId: "e2e-user-1",
  email: "admin@example.com",
  role: "admin",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
};

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

    if (path === "/documents" && request.method() === "GET") {
      const statusFilter = requestUrl.searchParams.get("status");
      const items = [
        {
          document_id: "doc-1",
          filename: "Employee-Handbook.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 12,
          chunk_count: 42,
          error_message: null,
          error_details: null,
          created_at: "2026-05-19T09:30:00Z",
          updated_at: "2026-05-20T08:30:00Z",
        },
      ];
      const filtered = statusFilter
        ? items.filter((item) => item.status === statusFilter)
        : items;
      await fulfillJson(route, {
        items: filtered,
        total: filtered.length,
        limit: Number.parseInt(
          requestUrl.searchParams.get("limit") ?? "20",
          10,
        ),
        offset: Number.parseInt(
          requestUrl.searchParams.get("offset") ?? "0",
          10,
        ),
        status: statusFilter,
        sort_by: requestUrl.searchParams.get("sort_by") ?? "updated_at",
        sort_order: requestUrl.searchParams.get("sort_order") ?? "desc",
      });
      return;
    }

    if (path === "/documents/doc-1" && request.method() === "GET") {
      await fulfillJson(route, {
        document_id: "doc-1",
        filename: "Employee-Handbook.pdf",
        file_type: "pdf",
        status: "indexed",
        page_count: 12,
        chunk_count: 42,
        checksum: "sha256:e2e-doc-1",
        error_message: null,
        error_details: null,
        language: "en",
        chunking_diagnostics: {
          strategy: "adaptive_hybrid",
          selected_strategy: "page_aware",
          profile_version: "1.0",
          profile_source: "custom_profile",
          chunk_size_tokens: 700,
          chunk_overlap_tokens: 120,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          ocr_applied: true,
          hierarchical_mode: false,
          parent_chunk_count: null,
          child_chunk_count: null,
          reason_codes: ["pdf_ocr_applied"],
          adaptive_signals: {
            file_type: "pdf",
            page_count: 12,
            total_token_count: 5200,
            ocr_applied: true,
            heading_density: 0.3,
            avg_chars_per_page: null,
            avg_paragraph_tokens: null,
          },
          token_distribution: {
            min_tokens: 120,
            max_tokens: 260,
            avg_tokens: 188.5,
            total_tokens: 7917,
          },
        },
        lifecycle_timeline: [
          {
            step: "index",
            label: "Index",
            description: "Upsert embedded chunks into vector storage.",
            status: "completed",
            document_id: "doc-1",
            pipeline_run_id: "run-doc-1",
            pipeline_type: "document.process",
            started_at: "2026-05-20T08:20:00Z",
            completed_at: "2026-05-20T08:25:00Z",
            duration_ms: 300000,
            logs: ["upserted 42 chunks"],
          },
        ],
        created_at: "2026-05-19T09:30:00Z",
        updated_at: "2026-05-20T08:30:00Z",
      });
      return;
    }

    if (path === "/documents/doc-1/status" && request.method() === "GET") {
      await fulfillJson(route, {
        document_id: "doc-1",
        status: "indexed",
        error_message: null,
        error_details: null,
        updated_at: "2026-05-20T08:30:00Z",
      });
      return;
    }

    if (path === "/documents/doc-1/chunks" && request.method() === "GET") {
      await fulfillJson(route, {
        document_id: "doc-1",
        items: [
          {
            chunk_id: "chunk-1",
            page_number: 1,
            chunk_index: 1,
            token_count: 180,
            embedding_model: "text-embedding-3-small",
            index_version: "v1",
            section_path: "Handbook > Introduction",
            language: "en",
            chunk_level: 0,
            child_count: 0,
            source_start_offset: 0,
            source_end_offset: 280,
            text_preview: "Rudix processes enterprise documents securely.",
            text: null,
            created_at: "2026-05-20T08:10:00Z",
          },
        ],
        total: 1,
        limit: Number.parseInt(requestUrl.searchParams.get("limit") ?? "8", 10),
        offset: Number.parseInt(
          requestUrl.searchParams.get("offset") ?? "0",
          10,
        ),
        include_full_text:
          requestUrl.searchParams.get("include_full_text") === "true",
      });
      return;
    }

    if (path === "/documents/doc-1/reindex" && request.method() === "POST") {
      await fulfillJson(
        route,
        {
          document_id: "doc-1",
          status: "processing",
          queue_status: "queued",
        },
        202,
      );
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
          {
            name: "page_aware",
            display_name: "Page Aware",
            description:
              "Preserves page boundaries for citation-heavy documents.",
            suitable_for: ["pdf", "ocr", "evidence packets"],
            requires_page_structure: true,
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

    if (
      path === "/admin/chunking-profiles/preview" &&
      request.method() === "POST"
    ) {
      await fulfillJson(route, {
        strategy_used: "page_aware",
        chunk_count: 6,
        min_tokens: 90,
        max_tokens: 210,
        avg_tokens: 153.5,
        total_tokens: 921,
        reason_codes: ["pdf_ocr_applied"],
        sample_chunks: [
          {
            chunk_index: 0,
            token_count: 180,
            section_path: "Handbook > Introduction",
            chunk_level: 0,
            is_parent: false,
          },
        ],
        warnings: [],
      });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            session_id: "session-1",
            title: "Onboarding FAQ",
            message_count: 2,
            created_at: "2026-05-20T07:00:00Z",
            updated_at: "2026-05-20T08:00:00Z",
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
      return;
    }

    if (
      path === "/chat/sessions/session-1/messages" &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, {
        items: [
          {
            message_id: "m-1",
            role: "user",
            content: "How do we upload files?",
            confidence_score: null,
            confidence_category: null,
            citations: [],
            created_at: "2026-05-20T08:00:00Z",
          },
          {
            message_id: "m-2",
            role: "assistant",
            content: "Use the upload modal on the Documents page.",
            confidence_score: 0.82,
            confidence_category: "high",
            citations: [],
            created_at: "2026-05-20T08:00:03Z",
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "POST") {
      await fulfillJson(
        route,
        {
          session_id: "session-new",
          title: null,
          message_count: 0,
          created_at: "2026-05-20T08:10:00Z",
          updated_at: "2026-05-20T08:10:00Z",
        },
        201,
      );
      return;
    }

    if (path === "/chat" && request.method() === "POST") {
      await fulfillJson(route, {
        chat_session_id: "session-new",
        message_id: "assistant-msg-1",
        answer: "Mocked answer from e2e test.",
        confidence_score: 0.79,
        confidence_category: "medium",
        confidence_explanation: {
          top_similarity: 0.81,
          average_similarity: 0.7,
          top_rerank_score: 0.75,
          citation_support_score: 0.8,
          citation_validation_score: 0.9,
          citation_coverage_score: 0.84,
          retrieval_agreement_score: 0.78,
          raw_score: 0.79,
          citation_validation_multiplier: 1,
          not_found_penalty_multiplier: 1,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        debug: {
          latencies_ms: { total: 320 },
          retrieval_count: 4,
          selected_count: 2,
          rerank_applied: true,
          embedding_model: "text-embedding-3-small",
          llm_model: "gpt-5.4-mini",
        },
        created_at: "2026-05-20T08:10:20Z",
      });
      return;
    }

    if (path === "/evaluation-sets" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            evaluation_set_id: "set-1",
            name: "Regression Set",
            description: "Baseline checks",
            question_count: 1,
            created_at: "2026-05-20T07:30:00Z",
            updated_at: "2026-05-20T08:30:00Z",
          },
        ],
        total: 1,
        limit: 100,
        offset: 0,
      });
      return;
    }

    if (
      path === "/evaluation-sets/set-1/questions" &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, {
        evaluation_set_id: "set-1",
        items: [
          {
            evaluation_question_id: "q-1",
            evaluation_set_id: "set-1",
            question: "What is the SLA?",
            expected_answer: "99.9%",
            expected_document_id: "doc-1",
            expected_page_number: 4,
            tags: ["sla"],
            metadata: {},
            created_at: "2026-05-20T07:30:00Z",
            updated_at: "2026-05-20T08:30:00Z",
          },
        ],
        total: 1,
        limit: 200,
        offset: 0,
      });
      return;
    }

    if (path === "/evaluations/run" && request.method() === "POST") {
      await fulfillJson(
        route,
        {
          evaluation_run_id: "run-e2e-1",
          status: "queued",
        },
        202,
      );
      return;
    }

    if (path === "/evaluations/runs/run-e2e-1" && request.method() === "GET") {
      await fulfillJson(route, {
        evaluation_run_id: "run-e2e-1",
        evaluation_set_id: "set-1",
        status: "completed",
        config: { top_k: 5, rerank: true, run_name: "E2E evaluation run" },
        summary: {
          question_total_count: 1,
          question_success_count: 1,
          question_failure_count: 0,
          retrieval_hit_rate: 1,
          faithfulness_score: 0.9,
          answer_relevance_score: 0.9,
          citation_accuracy_score: 0.9,
          latency_ms_average: 180,
          cost_usd_total: 0.02,
        },
        failure_reason: null,
        failure_type: null,
        started_at: "2026-05-20T08:00:00Z",
        completed_at: "2026-05-20T08:01:00Z",
        created_at: "2026-05-20T08:00:00Z",
        updated_at: "2026-05-20T08:01:00Z",
        results: {
          items: [
            {
              evaluation_result_id: "r-1",
              evaluation_question_id: "q-1",
              question: "What is the SLA?",
              status: "completed",
              generated_answer: "99.9%",
              retrieval_score: 1,
              faithfulness_score: 0.9,
              citation_accuracy_score: 0.9,
              answer_relevance_score: 0.9,
              latency_ms: 180,
              metrics: {},
              failure_reason: null,
              failure_type: null,
              details: {},
              created_at: "2026-05-20T08:00:30Z",
              updated_at: "2026-05-20T08:00:30Z",
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        },
      });
      return;
    }

    if (path === "/admin/usage" && request.method() === "GET") {
      await fulfillJson(route, {
        organization_id: ORG_ID,
        range: { from: "2026-04-21", to: "2026-05-20" },
        granularity: "day",
        totals: {
          input_tokens: 1000,
          output_tokens: 250,
          cost_usd: 2.4,
          event_count: 7,
          avg_confidence: 0.77,
          avg_latency_ms: 250,
        },
        series: [],
      });
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

    if (path === "/notifications/unread-count" && request.method() === "GET") {
      await fulfillJson(route, { unread_count: 1 });
      return;
    }

    if (path === "/notifications" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            notification_id: "notif-e2e-1",
            event_type: "upload_failed",
            severity: "error",
            title: "Document processing failed",
            message:
              "The document could not be indexed. Check the document details for more information.",
            href: "/documents?highlight=doc-1",
            source_id: "doc-1",
            is_read: false,
            created_at: "2026-05-20T08:30:00Z",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        unread_count: 1,
      });
      return;
    }

    if (
      path === "/notifications/notif-e2e-1/read" &&
      request.method() === "PATCH"
    ) {
      await fulfillJson(route, {
        notification_id: "notif-e2e-1",
        is_read: true,
      });
      return;
    }

    if (
      path === "/notifications/mark-all-read" &&
      request.method() === "POST"
    ) {
      await fulfillJson(route, { marked_count: 1 });
      return;
    }

    await fulfillJson(
      route,
      { detail: `No e2e mock for ${request.method()} ${path}` },
      404,
    );
  });
}

async function seedAuthenticatedSession(
  page: Page,
  session: TestSession = baseSession,
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

test.describe("frontend e2e smoke (no real backend)", () => {
  test("navigates public marketing routes and login CTA", async ({ page }) => {
    await page.goto("/");
    const primaryNavigation = page.getByRole("navigation", {
      name: "Primary navigation",
    });
    const headerActions = page.locator("header");

    await expect(
      page.getByRole("heading", { name: /Ask your documents/i }),
    ).toBeVisible();

    await primaryNavigation
      .getByRole("link", { name: "Solutions", exact: true })
      .click();
    await expect(page).toHaveURL(/\/solutions$/);
    await expect(
      page.getByRole("heading", {
        name: "AI document Q&A for every team.",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Request Demo" }).first(),
    ).toBeVisible();
    await page.waitForLoadState("networkidle");

    await primaryNavigation
      .getByRole("link", { name: "Security", exact: true })
      .click();
    await expect(page).toHaveURL(/\/security$/);
    await expect(
      page.getByRole("heading", {
        name: "Security-first document AI for trusted enterprise knowledge",
      }),
    ).toBeVisible();

    await primaryNavigation
      .getByRole("link", { name: "Pricing", exact: true })
      .click();
    await expect(page).toHaveURL(/\/pricing$/);
    await expect(
      page.getByRole("heading", {
        name: "Choose a plan for trusted document AI operations",
      }),
    ).toBeVisible();

    await page.goto("/demo");
    await expect(page).toHaveURL(/\/contact$/);
    await expect(
      page.getByRole("heading", {
        name: "Speak with us about your document workflow",
      }),
    ).toBeVisible();

    const productLink = primaryNavigation.getByRole("link", {
      name: "Product",
      exact: true,
    });
    const configuredProductHref = await productLink.getAttribute("href");
    const configuredProductPath = new URL(
      configuredProductHref ?? "/product",
      "http://localhost:3001",
    ).pathname;
    const escapedConfiguredProductPath = configuredProductPath.replace(
      /[.*+?^${}()|[\]\\]/g,
      "\\$&",
    );

    await productLink.click();
    await expect(page).toHaveURL(
      new RegExp(`${escapedConfiguredProductPath}$`),
    );
    await expect(
      page.getByRole("heading", {
        name: /The Infrastructure for High-Fidelity/i,
      }),
    ).toBeVisible();

    await headerActions
      .getByRole("link", { name: "Login", exact: true })
      .click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("redirects protected route to login and signs in successfully", async ({
    page,
  }) => {
    await installApiMocks(page);
    await page.goto("/documents");
    await waitForSessionBootstrap(page);

    const loginEmail = page.getByLabel("Email");
    const documentsHeading = page.getByRole("heading", {
      name: "Upload Documents",
    });

    await Promise.race([
      loginEmail.waitFor({ state: "visible", timeout: 30_000 }),
      documentsHeading.waitFor({ state: "visible", timeout: 30_000 }),
    ]);

    if (await loginEmail.isVisible().catch(() => false)) {
      await page.getByLabel("Email").fill("admin@example.com");
      await page.getByLabel("Password").fill("123123123");
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page).toHaveURL(/\/documents$/);
    }

    await expect(documentsHeading).toBeVisible();
  });

  test("loads dashboard with mocked APIs while authenticated", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/dashboard");
    await waitForSessionBootstrap(page);
    await expect(
      page.getByRole("heading", { name: "Enterprise RAG Command Center" }),
    ).toBeVisible();
    await expect(page.getByText("Recent activity")).toBeVisible();
  });

  test("loads documents and chat routes with mocked data", async ({ page }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/documents");
    await waitForSessionBootstrap(page);
    await expect(
      page.getByRole("heading", {
        name: "Upload Documents",
      }),
    ).toBeVisible();
    await expect(page.getByText("Employee-Handbook.pdf")).toBeVisible();

    await page.goto("/chat");
    await waitForSessionBootstrap(page);
    await expect(
      page.getByRole("heading", { name: "Chat Session" }),
    ).toBeVisible();
    await expect(page.getByText("Onboarding FAQ")).toBeVisible();
    await expect(
      page.getByPlaceholder("Type a message or use '/' for commands..."),
    ).toBeVisible();
  });

  test("shows organization chunking profile defaults", async ({ page }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/settings?tab=organization");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Chunking Profiles" }),
    ).toBeVisible();
    await expect(page.getByLabel("Profile Name")).toHaveValue(
      "Operations Default",
    );
  });

  test("shows document chunk diagnostics and queues re-index", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/documents/doc-1");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", { name: "Employee-Handbook.pdf" }),
    ).toBeVisible();
    await expect(page.getByText("Chunking diagnostics")).toBeVisible();

    page.once("dialog", (dialog) => void dialog.accept());
    await page.getByRole("button", { name: "Queue re-index" }).click();

    await expect(
      page.getByText(/Re-index requested using Operations Default/i),
    ).toBeVisible();
  });

  test("opens evaluations and starts a mocked evaluation run", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/evaluations");
    await waitForSessionBootstrap(page);

    await expect(
      page.getByRole("heading", {
        name: "Track RAG quality before shipping answers",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Evaluation datasets" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Regression Set", exact: true }),
    ).toBeVisible();

    await page
      .getByRole("button", { name: "Start evaluation run", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Start evaluation run" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Queue run" }).click();

    await expect(page).toHaveURL(/\/evaluations\/runs\/run-e2e-1$/, {
      timeout: 15_000,
    });
    await expect(page.getByText("Run detail")).toBeVisible();
    await expect(page.getByText("Case results")).toBeVisible();
  });

  test("shows upload failure notification and deep-links to document", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/dashboard");
    await waitForSessionBootstrap(page);

    // Bell badge shows the unread count from the polling query.
    await expect(page.getByLabel("Notifications")).toBeVisible();

    // Open the notification center.
    await page.getByLabel("Notifications").click();

    // The failed document notification should be visible.
    await expect(page.getByText("Document processing failed")).toBeVisible();
    await expect(page.getByText(/could not be indexed/)).toBeVisible();

    // Clicking the notification navigates to the documents page.
    const notifLink = page.getByRole("menuitem", {
      name: /Document processing failed/,
    });
    await notifLink.click();

    await expect(page).toHaveURL(/\/documents/);
  });
});
