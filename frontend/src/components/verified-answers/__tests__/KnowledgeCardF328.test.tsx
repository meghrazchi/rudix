import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeCard } from "@/components/verified-answers/KnowledgeCard";
import type { VerifiedAnswerResponse } from "@/lib/api/verified-answers";

// ── mocks ──────────────────────────────────────────────────────────────────────

const mockPermissions = vi.hoisted(() => ({
  hasPermission: vi.fn(() => true),
  hasAnyPermission: vi.fn(() => true),
  hasAllPermissions: vi.fn(() => true),
  role: "admin" as string | null,
  permissions: new Set<string>(),
}));

const mockApi = vi.hoisted(() => ({
  submitForReview: vi.fn(),
  approveVerifiedAnswer: vi.fn(),
  rejectVerifiedAnswer: vi.fn(),
  publishVerifiedAnswer: vi.fn(),
  archiveVerifiedAnswer: vi.fn(),
  deprecateVerifiedAnswer: vi.fn(),
  restoreVerifiedAnswer: vi.fn(),
  duplicateVerifiedAnswer: vi.fn(),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/verified-answers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/verified-answers")>();
  return {
    ...actual,
    submitForReview: (...args: unknown[]) => mockApi.submitForReview(...args),
    approveVerifiedAnswer: (...args: unknown[]) =>
      mockApi.approveVerifiedAnswer(...args),
    rejectVerifiedAnswer: (...args: unknown[]) =>
      mockApi.rejectVerifiedAnswer(...args),
    publishVerifiedAnswer: (...args: unknown[]) =>
      mockApi.publishVerifiedAnswer(...args),
    archiveVerifiedAnswer: (...args: unknown[]) =>
      mockApi.archiveVerifiedAnswer(...args),
    deprecateVerifiedAnswer: (...args: unknown[]) =>
      mockApi.deprecateVerifiedAnswer(...args),
    restoreVerifiedAnswer: (...args: unknown[]) =>
      mockApi.restoreVerifiedAnswer(...args),
    duplicateVerifiedAnswer: (...args: unknown[]) =>
      mockApi.duplicateVerifiedAnswer(...args),
  };
});

vi.mock("@/components/chat/DocumentPreviewModal", () => ({
  CitationPreviewDrawer: () => null,
}));

// ── helpers ────────────────────────────────────────────────────────────────────

function makeAnswer(
  overrides: Partial<VerifiedAnswerResponse> = {},
): VerifiedAnswerResponse {
  return {
    answer_id: "00000000-0000-0000-0000-000000000001",
    organization_id: "00000000-0000-0000-0000-000000000099",
    title: "Test Card",
    question: "What is X?",
    answer_text: "X is a thing.",
    status: "draft",
    tags: null,
    collection_id: null,
    owner_id: null,
    requires_citations: false,
    review_date: null,
    expiry_date: null,
    approved_by_id: null,
    approved_at: null,
    published_at: null,
    deprecated_at: null,
    restored_at: null,
    rejection_note: null,
    source_message_id: null,
    created_by_id: null,
    is_stale: false,
    citations: [],
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    ...overrides,
  };
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockPermissions.role = "admin";
  // confirm() always returns true in tests
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

// ── tests ──────────────────────────────────────────────────────────────────────

describe("KnowledgeCard F328 — deprecated status", () => {
  it("shows deprecated warning banner for deprecated cards", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "deprecated" })}
        queryKey={[]}
      />,
    );
    expect(screen.getByText(/has been deprecated/i)).toBeInTheDocument();
  });

  it("shows Deprecated badge for deprecated cards", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "deprecated" })}
        queryKey={[]}
      />,
    );
    expect(screen.getByText("Deprecated")).toBeInTheDocument();
  });

  it("shows Restore button for deprecated cards (admin)", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "deprecated" })}
        queryKey={[]}
      />,
    );
    expect(
      screen.getByRole("button", { name: /restore/i }),
    ).toBeInTheDocument();
  });

  it("calls restoreVerifiedAnswer when Restore is clicked", async () => {
    mockApi.restoreVerifiedAnswer.mockResolvedValue(
      makeAnswer({ status: "draft" }),
    );
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "deprecated" })}
        queryKey={[]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /restore/i }));
    await waitFor(() =>
      expect(mockApi.restoreVerifiedAnswer).toHaveBeenCalledWith(
        "00000000-0000-0000-0000-000000000001",
      ),
    );
  });
});

describe("KnowledgeCard F328 — published card actions", () => {
  it("shows Deprecate button for published cards (admin)", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "published" })}
        queryKey={[]}
      />,
    );
    expect(
      screen.getByRole("button", { name: /deprecate/i }),
    ).toBeInTheDocument();
  });

  it("calls deprecateVerifiedAnswer when Deprecate is confirmed", async () => {
    mockApi.deprecateVerifiedAnswer.mockResolvedValue(
      makeAnswer({ status: "deprecated" }),
    );
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "published" })}
        queryKey={[]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /deprecate/i }));
    await waitFor(() =>
      expect(mockApi.deprecateVerifiedAnswer).toHaveBeenCalledWith(
        "00000000-0000-0000-0000-000000000001",
      ),
    );
  });
});

describe("KnowledgeCard F328 — duplicate action", () => {
  it("shows Duplicate button for writer roles", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "draft" })}
        queryKey={[]}
      />,
    );
    expect(
      screen.getByRole("button", { name: /duplicate/i }),
    ).toBeInTheDocument();
  });

  it("calls duplicateVerifiedAnswer when Duplicate is clicked", async () => {
    mockApi.duplicateVerifiedAnswer.mockResolvedValue(
      makeAnswer({ answer_id: "copy-id" }),
    );
    const onDuplicated = vi.fn();
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "draft" })}
        queryKey={[]}
        onDuplicated={onDuplicated}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /duplicate/i }));
    await waitFor(() =>
      expect(mockApi.duplicateVerifiedAnswer).toHaveBeenCalledWith(
        "00000000-0000-0000-0000-000000000001",
      ),
    );
    await waitFor(() => expect(onDuplicated).toHaveBeenCalledWith("copy-id"));
  });

  it("hides Duplicate for viewer roles", () => {
    mockPermissions.role = "viewer";
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "draft" })}
        queryKey={[]}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /duplicate/i }),
    ).not.toBeInTheDocument();
  });
});

describe("KnowledgeCard F328 — archived card restore", () => {
  it("shows Restore button for archived cards", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "archived" })}
        queryKey={[]}
      />,
    );
    expect(
      screen.getByRole("button", { name: /restore/i }),
    ).toBeInTheDocument();
  });

  it("does not show Archive button when card is restorable", () => {
    wrap(
      <KnowledgeCard
        answer={makeAnswer({ status: "archived" })}
        queryKey={[]}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /^archive$/i }),
    ).not.toBeInTheDocument();
  });
});
