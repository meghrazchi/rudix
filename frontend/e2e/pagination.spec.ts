import { expect, test, type Page, type Route } from "@playwright/test";

import { mockCorsHeaders } from "./support/mock-cors";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";
const PAGE_SIZE = 20;
const TOTAL_DOCUMENTS = 30;

const session = {
  userId: "e2e-user-pagination",
  email: "admin@example.com",
  role: "admin" as const,
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
};

function documentRow(index: number) {
  return {
    document_id: `e2e-doc-${index}`,
    filename: `paged-${index}.pdf`,
    file_type: "pdf",
    status: "indexed",
    page_count: 1,
    chunk_count: 2,
    error_message: null,
    error_details: null,
    created_at: "2026-05-14T00:00:00Z",
    updated_at: "2026-05-15T00:00:00Z",
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json",
      ...mockCorsHeaders(route.request()),
    },
    body: JSON.stringify(body),
  });
}

/** Two keyset pages of documents (20 + 10) and empty side panels. */
async function installApiMocks(page: Page, cursorRequests: string[]) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");

    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: mockCorsHeaders(request) });
      return;
    }

    if (path === "/documents" && request.method() === "GET") {
      const limit = Number(url.searchParams.get("limit") ?? PAGE_SIZE);
      const cursor = url.searchParams.get("cursor");
      if (cursor) {
        cursorRequests.push(cursor);
      }
      const offset = cursor === "page-2" ? PAGE_SIZE : 0;
      const all = Array.from({ length: TOTAL_DOCUMENTS }, (_, i) =>
        documentRow(i + 1),
      );
      const items = all.slice(offset, offset + limit);
      await fulfillJson(route, {
        items,
        total: cursor ? null : TOTAL_DOCUMENTS,
        limit,
        offset: 0,
        next_cursor:
          !cursor && limit === PAGE_SIZE && TOTAL_DOCUMENTS > PAGE_SIZE
            ? "page-2"
            : null,
        status: null,
        sort_by: "created_at",
        sort_order: "desc",
      });
      return;
    }

    if (path === "/collections" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 50, offset: 0 });
      return;
    }

    if (path === "/notifications/unread-count") {
      await fulfillJson(route, { unread_count: 0 });
      return;
    }

    if (path === "/notifications") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
        unread_count: 0,
      });
      return;
    }

    if (path === "/auth/effective-permissions") {
      await fulfillJson(route, { permissions: [] });
      return;
    }

    await fulfillJson(
      route,
      { detail: `No e2e mock for ${request.method()} ${path}` },
      404,
    );
  });
}

test.describe("Pagination and large lists (R07-06)", () => {
  test("documents page shows a count, Load more, and appends the next page", async ({
    page,
  }) => {
    const cursorRequests: string[] = [];
    await installApiMocks(page, cursorRequests);
    await page.addInitScript(
      ({ storageKey, payload }) => {
        window.localStorage.setItem(storageKey, JSON.stringify(payload));
      },
      { storageKey: SESSION_STORAGE_KEY, payload: session },
    );

    await page.goto("/documents");

    const table = page.getByRole("table");
    await expect(table.getByText("paged-1.pdf")).toBeVisible({
      timeout: 30_000,
    });
    await expect(
      page.getByText("Showing 20 of 30", { exact: true }),
    ).toBeVisible();
    await expect(table.getByText("paged-21.pdf")).toHaveCount(0);

    await page.getByRole("button", { name: "Load more" }).click();

    await expect(table.getByText("paged-30.pdf")).toBeVisible();
    await expect(table.getByText("paged-1.pdf")).toBeVisible();
    await expect(
      page.getByText("Showing 30 of 30", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(
      0,
    );
    expect(cursorRequests).toContain("page-2");
  });
});
