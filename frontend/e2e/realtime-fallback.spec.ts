import { expect, test, type Page, type Route } from "@playwright/test";

import { mockCorsHeaders } from "./support/mock-cors";

/**
 * R07-07: polling never runs in a hidden tab. The default e2e server runs with realtime
 * off, so the documents page polls processing documents every 4 s while visible, stops
 * while `document.visibilityState` is "hidden", and resumes when visible again.
 */

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

const session = {
  userId: "e2e-user-realtime",
  email: "admin@example.com",
  role: "admin" as const,
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
};

function documentRow(index: number) {
  return {
    document_id: `e2e-rt-doc-${index}`,
    filename: `realtime-${index}.pdf`,
    file_type: "pdf",
    status: index === 1 ? "processing" : "indexed",
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

async function installApiMocks(page: Page, listRequests: number[]) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");

    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: mockCorsHeaders(request) });
      return;
    }
    if (path === "/documents" && request.method() === "GET") {
      const limit = Number(url.searchParams.get("limit") ?? 20);
      if (limit === 20 && !url.searchParams.get("status")) {
        listRequests.push(Date.now());
      }
      const items = Array.from({ length: Math.min(limit, 3) }, (_, i) =>
        documentRow(i + 1),
      );
      await fulfillJson(route, {
        items,
        total: 3,
        limit,
        offset: 0,
        next_cursor: null,
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

async function setVisibility(page: Page, state: "visible" | "hidden") {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => value,
    });
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => value === "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test.describe("Realtime-aware polling (R07-07)", () => {
  test("documents page stops polling while hidden and resumes when visible", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const listRequests: number[] = [];
    await installApiMocks(page, listRequests);
    await page.addInitScript(
      ({ storageKey, payload }) => {
        window.localStorage.setItem(storageKey, JSON.stringify(payload));
      },
      { storageKey: SESSION_STORAGE_KEY, payload: session },
    );

    await page.goto("/documents");
    await expect(
      page.getByRole("table").getByText("realtime-1.pdf"),
    ).toBeVisible({ timeout: 30_000 });

    // Visible: the processing document is polled (4 s).
    const visibleStart = listRequests.length;
    await expect
      .poll(() => listRequests.length - visibleStart, { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1);

    // Hidden: no list request for well over two intervals.
    await setVisibility(page, "hidden");
    await page.waitForTimeout(1_000); // a request already in flight may land
    const hiddenStart = listRequests.length;
    await page.waitForTimeout(10_000);
    expect(listRequests.length).toBe(hiddenStart);

    // Visible again: refetch on focus, then polling resumes.
    await setVisibility(page, "visible");
    await expect
      .poll(() => listRequests.length - hiddenStart, { timeout: 10_000 })
      .toBeGreaterThanOrEqual(1);
    const resumed = listRequests.length;
    await expect
      .poll(() => listRequests.length - resumed, { timeout: 15_000 })
      .toBeGreaterThanOrEqual(1);
  });
});
