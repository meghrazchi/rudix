import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateVerifiedAnswerModal } from "@/components/verified-answers/CreateVerifiedAnswerModal";
import type { VerifiedAnswerResponse } from "@/lib/api/verified-answers";

// ── mocks ──────────────────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  createVerifiedAnswer: vi.fn(),
  createVerifiedAnswerFromMessage: vi.fn(),
}));

vi.mock("@/lib/api/verified-answers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/verified-answers")>();
  return {
    ...actual,
    createVerifiedAnswer: (...args: unknown[]) =>
      mockApi.createVerifiedAnswer(...args),
    createVerifiedAnswerFromMessage: (...args: unknown[]) =>
      mockApi.createVerifiedAnswerFromMessage(...args),
  };
});

// ── helpers ────────────────────────────────────────────────────────────────────

function makeCreatedAnswer(): VerifiedAnswerResponse {
  return {
    answer_id: "new-answer-id",
    organization_id: "org-id",
    title: "Test card",
    question: "What?",
    answer_text: "This.",
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
    rejection_note: null,
    source_message_id: null,
    created_by_id: null,
    is_stale: false,
    citations: [],
    created_at: "2026-06-24T00:00:00Z",
    updated_at: "2026-06-24T00:00:00Z",
  };
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// ── tests ──────────────────────────────────────────────────────────────────────

describe("CreateVerifiedAnswerModal — manual mode", () => {
  const onClose = vi.fn();
  const onCreated = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.createVerifiedAnswer.mockResolvedValue(makeCreatedAnswer());
  });

  it("renders dialog with required fields", () => {
    wrap(
      <CreateVerifiedAnswerModal mode={{ kind: "manual" }} onClose={onClose} />,
    );
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(screen.getByLabelText(/title/i)).toBeDefined();
    expect(screen.getByLabelText(/canonical question/i)).toBeDefined();
    expect(screen.getByLabelText(/answer/i)).toBeDefined();
  });

  it("Create draft button is disabled when fields are empty", () => {
    wrap(
      <CreateVerifiedAnswerModal mode={{ kind: "manual" }} onClose={onClose} />,
    );
    const btn = screen.getByRole("button", { name: /create draft/i });
    expect(btn).toHaveProperty("disabled", true);
  });

  it("enables Create draft when required fields are filled", async () => {
    wrap(
      <CreateVerifiedAnswerModal mode={{ kind: "manual" }} onClose={onClose} />,
    );
    await userEvent.type(screen.getByLabelText(/title/i), "My card");
    await userEvent.type(screen.getByLabelText(/canonical question/i), "Why?");
    await userEvent.type(screen.getByLabelText(/answer/i), "Because.");

    const btn = screen.getByRole("button", { name: /create draft/i });
    expect(btn).toHaveProperty("disabled", false);
  });

  it("calls createVerifiedAnswer with correct payload", async () => {
    wrap(
      <CreateVerifiedAnswerModal
        mode={{ kind: "manual" }}
        onClose={onClose}
        onCreated={onCreated}
      />,
    );
    await userEvent.type(screen.getByLabelText(/title/i), "My card");
    await userEvent.type(screen.getByLabelText(/canonical question/i), "Why?");
    await userEvent.type(screen.getByLabelText(/answer/i), "Because.");
    await userEvent.click(
      screen.getByRole("button", { name: /create draft/i }),
    );

    await waitFor(() =>
      expect(mockApi.createVerifiedAnswer).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "My card",
          question: "Why?",
          answer_text: "Because.",
        }),
      ),
    );
  });

  it("calls onCreated with answer_id after success", async () => {
    wrap(
      <CreateVerifiedAnswerModal
        mode={{ kind: "manual" }}
        onClose={onClose}
        onCreated={onCreated}
      />,
    );
    await userEvent.type(screen.getByLabelText(/title/i), "My card");
    await userEvent.type(screen.getByLabelText(/canonical question/i), "Why?");
    await userEvent.type(screen.getByLabelText(/answer/i), "Because.");
    await userEvent.click(
      screen.getByRole("button", { name: /create draft/i }),
    );
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith("new-answer-id"),
    );
  });

  it("calls onClose when Cancel is clicked", async () => {
    wrap(
      <CreateVerifiedAnswerModal mode={{ kind: "manual" }} onClose={onClose} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("CreateVerifiedAnswerModal — from-message mode", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.createVerifiedAnswerFromMessage.mockResolvedValue(
      makeCreatedAnswer(),
    );
  });

  it("shows from-message info banner", () => {
    wrap(
      <CreateVerifiedAnswerModal
        mode={{
          kind: "from-message",
          messageId: "msg-123",
          prefillAnswerText: "Prefilled.",
        }}
        onClose={onClose}
      />,
    );
    expect(screen.getByText(/promote to knowledge card/i)).toBeDefined();
    expect(
      screen.getByText(/draft knowledge card from the selected answer/i),
    ).toBeDefined();
  });

  it("Title is required, question is optional override", () => {
    wrap(
      <CreateVerifiedAnswerModal
        mode={{ kind: "from-message", messageId: "msg-123" }}
        onClose={onClose}
      />,
    );
    expect(screen.getByLabelText(/title/i)).toBeDefined();
    expect(screen.getByLabelText(/question.*optional/i)).toBeDefined();
    // Manual answer textarea should not appear
    expect(screen.queryByLabelText(/^answer/i)).toBeNull();
  });

  it("calls createVerifiedAnswerFromMessage on submit", async () => {
    wrap(
      <CreateVerifiedAnswerModal
        mode={{ kind: "from-message", messageId: "msg-123" }}
        onClose={onClose}
      />,
    );
    await userEvent.type(screen.getByLabelText(/title/i), "From chat card");
    await userEvent.click(
      screen.getByRole("button", { name: /create draft/i }),
    );
    await waitFor(() =>
      expect(mockApi.createVerifiedAnswerFromMessage).toHaveBeenCalledWith(
        "msg-123",
        expect.objectContaining({ title: "From chat card" }),
      ),
    );
  });
});
