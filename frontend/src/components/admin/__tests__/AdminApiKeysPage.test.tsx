import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiKeysPage } from "@/components/admin/AdminApiKeysPage";
import type {
  ApiKey,
  ApiKeyCreated,
  ApiKeyListResponse,
} from "@/lib/api/api-keys";
import type { SessionState } from "@/lib/auth-session";

// ─── mocks ───────────────────────────────────────────────────────────────────

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: { role: "admin" },
  } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  updateApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  rotateApiKey: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/api/api-keys", () => ({
  listApiKeys: (...args: unknown[]) => mockApi.listApiKeys(...args),
  createApiKey: (...args: unknown[]) => mockApi.createApiKey(...args),
  updateApiKey: (...args: unknown[]) => mockApi.updateApiKey(...args),
  revokeApiKey: (...args: unknown[]) => mockApi.revokeApiKey(...args),
  rotateApiKey: (...args: unknown[]) => mockApi.rotateApiKey(...args),
  VALID_SCOPES: [
    "documents:read",
    "documents:write",
    "chat:write",
    "evaluations:run",
    "webhooks:manage",
    "connectors:manage",
  ],
}));

// ─── fixtures ────────────────────────────────────────────────────────────────

const BASE_KEY: ApiKey = {
  id: "key-1",
  organization_id: "org-1",
  name: "CI Integration",
  description: "Used by CI pipeline",
  key_prefix: "rudix_abc12345",
  scopes: ["documents:read", "chat:write"],
  status: "active",
  expires_at: null,
  last_used_at: null,
  created_by_id: "user-1",
  created_at: "2026-06-08T00:00:00Z",
  updated_at: "2026-06-08T00:00:00Z",
};

const REVOKED_KEY: ApiKey = {
  ...BASE_KEY,
  id: "key-2",
  name: "Old key",
  status: "revoked",
};

const EMPTY_LIST: ApiKeyListResponse = { items: [], total: 0 };

const LIST_WITH_KEYS: ApiKeyListResponse = {
  items: [BASE_KEY, REVOKED_KEY],
  total: 2,
};

const CREATED_KEY: ApiKeyCreated = {
  ...BASE_KEY,
  raw_key: "rudix_abc12345678901234567890abcdef",
};

// ─── helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminApiKeysPage />
    </QueryClientProvider>,
  );
}

function setRole(role: string) {
  mockAuth.state = {
    status: "authenticated",
    session: { role } as { role: string },
  } as SessionState;
}

// ─── tests ───────────────────────────────────────────────────────────────────

describe("AdminApiKeysPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setRole("admin");
  });

  it("shows loading state while fetching", () => {
    mockApi.listApiKeys.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders empty state when no keys exist", async () => {
    mockApi.listApiKeys.mockResolvedValue(EMPTY_LIST);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No active API keys/i)).toBeInTheDocument(),
    );
  });

  it("renders active and revoked key sections", async () => {
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("CI Integration")).toBeInTheDocument(),
    );
    expect(screen.getByText("Old key")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Revoked")).toBeInTheDocument();
  });

  it("shows key prefix and scopes on cards", async () => {
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByText(/rudix_abc12345/).length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText("documents:read").length).toBeGreaterThan(0);
    expect(screen.getAllByText("chat:write").length).toBeGreaterThan(0);
  });

  it("shows forbidden state for viewer role", async () => {
    setRole("viewer");
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/api_keys:list permission/i)).toBeInTheDocument(),
    );
  });

  it("opens create panel when button clicked", async () => {
    mockApi.listApiKeys.mockResolvedValue(EMPTY_LIST);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No active API keys/i)).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /\+ Create key/i }),
    );
    expect(screen.getByText("Create API Key")).toBeInTheDocument();
  });

  it("shows scope checkboxes in create panel", async () => {
    mockApi.listApiKeys.mockResolvedValue(EMPTY_LIST);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No active API keys/i)).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /Create key/i }));
    expect(screen.getByLabelText(/Documents — read/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Chat — write/i)).toBeInTheDocument();
  });

  it("creates a key and shows the copy-once banner", async () => {
    mockApi.listApiKeys.mockResolvedValue(EMPTY_LIST);
    mockApi.createApiKey.mockResolvedValue(CREATED_KEY);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No active API keys/i)).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /\+ Create key/i }),
    );
    await userEvent.type(
      screen.getByPlaceholderText(/e.g. CI integration key/i),
      "My key",
    );
    const createBtns = screen.getAllByRole("button", {
      name: /Create key/i,
      hidden: false,
    });
    await userEvent.click(createBtns[createBtns.length - 1]);
    await waitFor(() =>
      expect(
        screen.getByText(/This is the only time the full key is shown/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText("rudix_abc12345678901234567890abcdef"),
    ).toBeInTheDocument();
  });

  it("shows raw key only in copy-once banner, not in list", async () => {
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("CI Integration")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/rudix_abc12345678901234567890abcdef/),
    ).not.toBeInTheDocument();
  });

  it("shows revoke confirmation dialog", async () => {
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("CI Integration")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /Revoke/i }));
    expect(screen.getByText(/Revoke.*CI Integration/i)).toBeInTheDocument();
    expect(
      screen.getByText(/The key will stop working immediately/i),
    ).toBeInTheDocument();
  });

  it("calls revokeApiKey and closes dialog on confirm", async () => {
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    mockApi.revokeApiKey.mockResolvedValue(undefined);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("CI Integration")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /Revoke/i }));
    await userEvent.click(screen.getByRole("button", { name: /Revoke key/i }));
    await waitFor(() =>
      expect(mockApi.revokeApiKey).toHaveBeenCalledWith("key-1"),
    );
  });

  it("cancels revoke dialog without calling API", async () => {
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("CI Integration")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /Revoke/i }));
    await userEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(mockApi.revokeApiKey).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/Revoke "CI Integration"\?/i),
    ).not.toBeInTheDocument();
  });

  it("calls rotateApiKey and shows copy-once banner", async () => {
    const rotatedKey: ApiKeyCreated = {
      ...CREATED_KEY,
      id: "key-new",
      name: "CI Integration",
      raw_key: "rudix_newrotatedkey123456789012345",
    };
    mockApi.listApiKeys.mockResolvedValue(LIST_WITH_KEYS);
    mockApi.rotateApiKey.mockResolvedValue(rotatedKey);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("CI Integration")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /Rotate/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/This is the only time the full key is shown/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText("rudix_newrotatedkey123456789012345"),
    ).toBeInTheDocument();
  });

  it("hides create button and edit controls for viewer", async () => {
    setRole("viewer");
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/api_keys:list permission/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: /Create key/i }),
    ).not.toBeInTheDocument();
  });

  it("shows error state when API call fails", async () => {
    mockApi.listApiKeys.mockRejectedValue(new Error("Network error"));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Network error/i)).toBeInTheDocument(),
    );
  });
});
