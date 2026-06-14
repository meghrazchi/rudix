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

const session: TestSession = {
  userId: "e2e-user-graph",
  email: "viewer@example.com",
  role: "viewer",
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

    if (path === "/graph/entities" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            entity_id: "entity-1",
            entity_type: "Vendor",
            canonical_name: "Acme Corp",
            normalized_name: "acme corp",
            aliases: ["Acme"],
            alias_count: 1,
            workspace_id: "ws-1",
            external_source_id: "src-1",
            resolution_status: "verified",
            resolution_confidence: 0.92,
            confidence: 0.95,
            last_updated_at: "2026-06-14T10:00:00Z",
            evidence_count: 2,
            related_document_count: 1,
          },
        ],
        total: 1,
        skip: 0,
        limit: 20,
        query: requestUrl.searchParams.get("query"),
        entity_type: requestUrl.searchParams.get("entity_type"),
        min_confidence: null,
        source_document_id: null,
        source_connector: null,
        rel_type: null,
        relationship_direction: "both",
      });
      return;
    }

    if (
      path.startsWith("/graph/entities/entity-1") &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, {
        entity: {
          entity_id: "entity-1",
          entity_type: "Vendor",
          canonical_name: "Acme Corp",
          normalized_name: "acme corp",
          aliases: ["Acme"],
          alias_count: 1,
          workspace_id: "ws-1",
          external_source_id: "src-1",
          resolution_status: "verified",
          resolution_confidence: 0.92,
          confidence: 0.95,
          last_updated_at: "2026-06-14T10:00:00Z",
          evidence_count: 1,
          related_document_count: 1,
        },
        aliases: [],
        evidence: [
          {
            chunk_id: "chunk-1",
            source_document_id: "doc-1",
            workspace_id: "ws-1",
            document_version_id: "v1",
            page_number: 1,
            source_connector: "confluence",
            external_url: "https://example.com/doc-1",
            extraction_run_id: "run-1",
            confidence: 0.9,
            evidence_text: "Acme Corp is our vendor.",
            citation_text: "Acme Corp is our vendor.",
            citation_reference: "Policy p. 1",
            created_at: "2026-06-14T09:58:00Z",
          },
        ],
        relationships: [
          {
            relation_id: "rel-1",
            from_entity_id: "entity-1",
            rel_type: "OWNS",
            to_entity_id: "entity-2",
            status: "verified",
            confidence: 0.88,
            properties: { evidence_text: "Acme owns Contoso." },
          },
        ],
        connected_documents: [
          {
            document_id: "doc-1",
            page_numbers: [1],
            evidence_count: 1,
            max_confidence: 0.9,
            source_connectors: ["confluence"],
          },
        ],
        connected_entities: [
          {
            entity_id: "entity-2",
            entity_type: "Organization",
            canonical_name: "Contoso",
            normalized_name: "contoso",
            relation_count: 1,
          },
        ],
        summary: {
          alias_count: 1,
          evidence_count: 1,
          relationship_count: 1,
          connected_document_count: 1,
          connected_entity_count: 1,
        },
      });
      return;
    }

    if (path === "/documents/doc-1" && request.method() === "GET") {
      await fulfillJson(route, {
        document_id: "doc-1",
        filename: "Acme-policy.pdf",
        file_type: "pdf",
        status: "indexed",
        page_count: 2,
        chunk_count: 4,
        checksum: "sha256:e2e-doc-1",
        error_message: null,
        error_details: null,
        created_at: "2026-06-14T09:50:00Z",
        updated_at: "2026-06-14T10:00:00Z",
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
            token_count: 120,
            embedding_model: "text-embedding-3-small",
            index_version: "v1",
            section_path: "Policy > Vendor",
            language: "en",
            chunk_level: 0,
            child_count: 0,
            source_start_offset: 0,
            source_end_offset: 90,
            text_preview: "Acme Corp is our vendor.",
            text: null,
            created_at: "2026-06-14T09:58:00Z",
          },
        ],
        total: 1,
        limit: 8,
        offset: 0,
        include_full_text: false,
      });
      return;
    }

    if (path === "/documents/doc-1/status" && request.method() === "GET") {
      await fulfillJson(route, {
        document_id: "doc-1",
        status: "indexed",
        error_message: null,
        error_details: null,
        updated_at: "2026-06-14T10:00:00Z",
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
        user_id: "e2e-user-graph",
        email: "viewer@example.com",
        role: "viewer",
        organization_id: ORG_ID,
        organization_name: "Rudix E2E Org",
      });
      return;
    }

    await fulfillJson(
      route,
      { detail: `No graph e2e mock for ${request.method()} ${path}` },
      404,
    );
  });
}

async function seedAuthenticatedSession(page: Page): Promise<void> {
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

test.describe("Graph explorer smoke", () => {
  test("loads the graph explorer and opens an entity detail page", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/graph");
    await waitForSessionBootstrap(page);

    await expect(
      page
        .getByRole("main")
        .getByRole("heading", { name: "Graph explorer", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Acme Corp" })).toBeVisible();

    await page.goto("/graph/entities/entity-1");
    await expect(
      page.getByRole("main").getByRole("heading", {
        name: "Acme Corp",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("main")
        .getByRole("heading", { name: "Connected documents", exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("main")
        .getByRole("heading", { name: "Source evidence", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Open evidence" }),
    ).toBeVisible();
  });
});
