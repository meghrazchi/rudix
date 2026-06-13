import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminWebhooksPage } from "@/components/admin/AdminWebhooksPage";
import { ApiClientError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";
import type {
  Webhook,
  WebhookCreated,
  WebhookDelivery,
  WebhookDeliveryListResponse,
  WebhookListResponse,
} from "@/lib/api/webhooks";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listWebhooks: vi.fn(),
  createWebhook: vi.fn(),
  updateWebhook: vi.fn(),
  deleteWebhook: vi.fn(),
  rotateWebhookSecret: vi.fn(),
  testWebhook: vi.fn(),
  listWebhookDeliveries: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/webhooks", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/webhooks")>();
  return {
    ...original,
    listWebhooks: () => mockApi.listWebhooks(),
    createWebhook: (req: unknown) => mockApi.createWebhook(req),
    updateWebhook: (id: string, req: unknown) => mockApi.updateWebhook(id, req),
    deleteWebhook: (id: string) => mockApi.deleteWebhook(id),
    rotateWebhookSecret: (id: string) => mockApi.rotateWebhookSecret(id),
    testWebhook: (id: string) => mockApi.testWebhook(id),
    listWebhookDeliveries: (id: string) => mockApi.listWebhookDeliveries(id),
  };
});

function makeAdminSession(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      displayName: "Admin",
      organizationId: "org-1",
      role: "admin",
    },
  };
}

function makeWebhook(overrides: Partial<Webhook> = {}): Webhook {
  return {
    id: "wh-1",
    organization_id: "org-1",
    name: "Doc Events",
    description: null,
    url: "https://example.com/hook",
    secret_prefix: "whsec_abc",
    event_types: ["document.indexed"],
    status: "active",
    retry_policy: { max_attempts: 5, backoff_seconds: 60 },
    created_by_id: "user-1",
    created_at: "2026-06-13T10:00:00Z",
    updated_at: "2026-06-13T10:00:00Z",
    ...overrides,
  };
}

function makeWebhookCreated(overrides: Partial<WebhookCreated> = {}): WebhookCreated {
  return {
    ...makeWebhook(),
    raw_secret: "whsec_supersecretvalue123",
    ...overrides,
  };
}

function makeDelivery(overrides: Partial<WebhookDelivery> = {}): WebhookDelivery {
  return {
    id: "del-1",
    webhook_id: "wh-1",
    organization_id: "org-1",
    event_type: "document.indexed",
    payload: { event: "document.indexed" },
    status: "delivered",
    http_status_code: 200,
    response_body: "OK",
    attempt_count: 1,
    next_retry_at: null,
    error_message: null,
    created_at: "2026-06-13T10:01:00Z",
    updated_at: "2026-06-13T10:01:00Z",
    ...overrides,
  };
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage() {
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <AdminWebhooksPage />
    </QueryClientProvider>,
  );
  return qc;
}

const emptyList: WebhookListResponse = { items: [], total: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  mockState.authState = makeAdminSession();
});

describe("AdminWebhooksPage", () => {
  it("shows loading state initially", () => {
    mockApi.listWebhooks.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it("shows forbidden when user lacks webhooks:list permission", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u2",
        email: "viewer@example.com",
        displayName: "Viewer",
        organizationId: "org-1",
        role: "viewer",
      },
    };
    mockApi.listWebhooks.mockResolvedValue(emptyList);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/webhooks:list permission/i)).toBeInTheDocument(),
    );
  });

  it("shows empty state with add button for admin", async () => {
    mockApi.listWebhooks.mockResolvedValue(emptyList);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No active webhooks/i)).toBeInTheDocument(),
    );
    expect(screen.getAllByRole("button", { name: /Add webhook/i }).length).toBeGreaterThan(0);
  });

  it("renders webhook card when list has items", async () => {
    mockApi.listWebhooks.mockResolvedValue({
      items: [makeWebhook()],
      total: 1,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Doc Events")).toBeInTheDocument(),
    );
    expect(screen.getByText(/https:\/\/example\.com\/hook/i)).toBeInTheDocument();
    expect(screen.getByText("document.indexed")).toBeInTheDocument();
  });

  it("shows error state on API failure", async () => {
    mockApi.listWebhooks.mockRejectedValue(
      new ApiClientError("Server error", 500, false),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Server error/i)).toBeInTheDocument(),
    );
  });

  it("shows forbidden state on 403 response", async () => {
    mockApi.listWebhooks.mockRejectedValue(
      new ApiClientError("Forbidden", 403, false),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Access denied/i)).toBeInTheDocument(),
    );
  });

  it("opens create form panel on Add webhook click", async () => {
    mockApi.listWebhooks.mockResolvedValue(emptyList);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /\+ Add webhook/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Add webhook/i }));
    expect(screen.getByText("Create Webhook")).toBeInTheDocument();
  });

  it("calls createWebhook and shows secret banner on success", async () => {
    const created = makeWebhookCreated();
    mockApi.listWebhooks.mockResolvedValue(emptyList);
    mockApi.createWebhook.mockResolvedValue(created);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /\+ Add webhook/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Add webhook/i }));

    await user.type(screen.getByPlaceholderText(/e\.g\. Document events/i), "My hook");
    await user.type(
      screen.getByPlaceholderText(/https:\/\/your-server/i),
      "https://recv.example.com/hook",
    );
    await user.click(screen.getByRole("button", { name: /Create webhook/i }));

    await waitFor(() =>
      expect(mockApi.createWebhook).toHaveBeenCalledWith(
        expect.objectContaining({ name: "My hook" }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/Signing secret — copy it now/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(created.raw_secret)).toBeInTheDocument();
  });

  it("closes create form on Cancel", async () => {
    mockApi.listWebhooks.mockResolvedValue(emptyList);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /\+ Add webhook/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /\+ Add webhook/i }));
    expect(screen.getByText("Create Webhook")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(screen.queryByText("Create Webhook")).toBeNull();
  });

  it("opens delete confirmation dialog", async () => {
    mockApi.listWebhooks.mockResolvedValue({ items: [makeWebhook()], total: 1 });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Doc Events")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Delete/i }));
    expect(screen.getByText(/Delete "Doc Events"/i)).toBeInTheDocument();
  });

  it("calls deleteWebhook on confirmation", async () => {
    mockApi.listWebhooks.mockResolvedValue({ items: [makeWebhook()], total: 1 });
    mockApi.deleteWebhook.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Doc Events")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Delete$/i }));
    await user.click(screen.getByRole("button", { name: /Delete webhook/i }));

    await waitFor(() =>
      expect(mockApi.deleteWebhook).toHaveBeenCalledWith("wh-1"),
    );
  });

  it("calls rotateWebhookSecret and shows new secret banner", async () => {
    const rotated = makeWebhookCreated({ raw_secret: "whsec_newrotatedsecret" });
    mockApi.listWebhooks.mockResolvedValue({ items: [makeWebhook()], total: 1 });
    mockApi.rotateWebhookSecret.mockResolvedValue(rotated);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Doc Events")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Rotate secret/i }));

    await waitFor(() =>
      expect(mockApi.rotateWebhookSecret).toHaveBeenCalledWith("wh-1"),
    );
    expect(screen.getByText(rotated.raw_secret)).toBeInTheDocument();
  });

  it("calls testWebhook and shows success banner", async () => {
    const deliveryResult: WebhookDeliveryListResponse = {
      items: [makeDelivery()],
      total: 1,
    };
    mockApi.listWebhooks.mockResolvedValue({ items: [makeWebhook()], total: 1 });
    mockApi.testWebhook.mockResolvedValue(deliveryResult);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Doc Events")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Send test/i }));

    await waitFor(() =>
      expect(mockApi.testWebhook).toHaveBeenCalledWith("wh-1"),
    );
    await waitFor(() =>
      expect(screen.getByText(/Test delivery succeeded/i)).toBeInTheDocument(),
    );
  });

  it("shows delivery log drawer with deliveries", async () => {
    const deliveries: WebhookDeliveryListResponse = {
      items: [makeDelivery(), makeDelivery({ id: "del-2", status: "failed", http_status_code: 500 })],
      total: 2,
    };
    mockApi.listWebhooks.mockResolvedValue({ items: [makeWebhook()], total: 1 });
    mockApi.listWebhookDeliveries.mockResolvedValue(deliveries);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Doc Events")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Delivery log/i }));

    await waitFor(() =>
      expect(mockApi.listWebhookDeliveries).toHaveBeenCalledWith("wh-1"),
    );
    await waitFor(() =>
      expect(screen.getAllByText(/Delivered/i).length).toBeGreaterThan(0),
    );
    expect(screen.getByText(/Failed/i)).toBeInTheDocument();
  });

  it("renders disabled webhooks in separate section", async () => {
    mockApi.listWebhooks.mockResolvedValue({
      items: [makeWebhook({ id: "wh-2", name: "Paused hook", status: "disabled" })],
      total: 1,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Disabled webhooks")).toBeInTheDocument(),
    );
    expect(screen.getByText("Paused hook")).toBeInTheDocument();
  });
});
