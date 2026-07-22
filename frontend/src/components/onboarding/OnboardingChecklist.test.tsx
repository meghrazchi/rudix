"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";

import { OnboardingChecklist } from "@/components/onboarding/OnboardingChecklist";
import type { AuthenticatedSession } from "@/lib/auth-session";
import {
  createDefaultOnboardingState,
  type OnboardingState,
} from "@/lib/onboarding";
import enMessages from "@/i18n/messages/en.json";

const mockApi = vi.hoisted(() => ({
  getOnboardingConfig: vi.fn(),
  loadSampleDataset: vi.fn(),
  listDocuments: vi.fn(),
  listChatSessions: vi.fn(),
}));

vi.mock("@/lib/api/onboarding", () => ({
  getOnboardingConfig: () => mockApi.getOnboardingConfig(),
  loadSampleDataset: () => mockApi.loadSampleDataset(),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: () => mockApi.listDocuments(),
}));

vi.mock("@/lib/api/chat", () => ({
  listChatSessions: () => mockApi.listChatSessions(),
}));

vi.mock("@/lib/analytics", () => ({
  trackOnboardingEvent: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/onboarding", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/onboarding")>();
  return {
    ...actual,
    writeOnboardingState: vi.fn(),
  };
});

function makeOwnerSession(): AuthenticatedSession {
  return {
    userId: "user-1",
    email: "owner@example.com",
    role: "owner",
    organizationId: "org-1",
    organizationName: "Test Org",
  };
}

function makeEmptyDocsResponse() {
  return {
    items: [],
    total: 0,
    limit: 200,
    offset: 0,
    sort_by: "updated_at" as const,
    sort_order: "desc" as const,
  };
}

function makeIndexedDocsResponse() {
  return {
    items: [
      {
        document_id: "doc-1",
        filename: "report.pdf",
        file_type: "pdf" as const,
        status: "indexed" as const,
        chunk_count: 10,
        created_at: "2026-06-25T00:00:00Z",
        updated_at: "2026-06-25T01:00:00Z",
      },
    ],
    total: 1,
    limit: 200,
    offset: 0,
    sort_by: "updated_at" as const,
    sort_order: "desc" as const,
  };
}

function makeEmptyChatResponse() {
  return { items: [], total: 0, limit: 1, offset: 0 };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

type RenderProps = {
  session?: AuthenticatedSession;
  state?: OnboardingState;
  onStateChange?: (next: OnboardingState) => void;
  onDismiss?: () => void;
};

function renderChecklist({
  session = makeOwnerSession(),
  state = createDefaultOnboardingState(),
  onStateChange = vi.fn(),
  onDismiss = vi.fn(),
}: RenderProps = {}) {
  const qc = makeQueryClient();
  render(
    <NextIntlClientProvider locale="en" messages={enMessages}>
      <QueryClientProvider client={qc}>
        <OnboardingChecklist
          session={session}
          state={state}
          onStateChange={onStateChange}
          onDismiss={onDismiss}
        />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
  return { qc, onStateChange, onDismiss };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getOnboardingConfig.mockResolvedValue({
    sample_docs_enabled: false,
    reset_at: null,
  });
  mockApi.listDocuments.mockResolvedValue(makeEmptyDocsResponse());
  mockApi.listChatSessions.mockResolvedValue(makeEmptyChatResponse());
});

describe("OnboardingChecklist", () => {
  it("renders the expanded checklist with progress bar and steps", async () => {
    renderChecklist();
    await waitFor(() =>
      expect(screen.getByText("Getting started")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("progressbar", { name: /setup.*complete/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Upload your first document")).toBeInTheDocument();
    expect(screen.getByText("Ask your first question")).toBeInTheDocument();
  });

  it("collapses to a compact trigger when collapse button is clicked", async () => {
    const user = userEvent.setup();
    renderChecklist();
    await waitFor(() =>
      expect(screen.getByLabelText("Collapse checklist")).toBeInTheDocument(),
    );
    await user.click(screen.getByLabelText("Collapse checklist"));
    expect(
      screen.getByLabelText("Open getting started checklist"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("re-expands when the collapsed trigger is clicked", async () => {
    const user = userEvent.setup();
    renderChecklist();
    await waitFor(() =>
      expect(screen.getByLabelText("Collapse checklist")).toBeInTheDocument(),
    );
    await user.click(screen.getByLabelText("Collapse checklist"));
    await user.click(screen.getByLabelText("Open getting started checklist"));
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("marks auto-detectable steps complete when documents are indexed", async () => {
    mockApi.listDocuments.mockResolvedValue(makeIndexedDocsResponse());
    renderChecklist();
    await waitFor(() => {
      const uploadItem = screen
        .getByText("Upload your first document")
        .closest("li");
      expect(uploadItem?.textContent).toContain("(complete)");
    });
  });

  it("marks a step as manually done when 'Mark done' is clicked", async () => {
    const user = userEvent.setup();
    const onStateChange = vi.fn();
    renderChecklist({ onStateChange });
    await waitFor(() =>
      expect(screen.getByText("Inspect citations")).toBeInTheDocument(),
    );
    const markDoneButtons = screen.getAllByText("Mark done");
    await user.click(markDoneButtons[0]);
    expect(onStateChange).toHaveBeenCalledWith(
      expect.objectContaining({
        manuallyCompleted: expect.arrayContaining([expect.any(String)]),
      }),
    );
  });

  it("calls onDismiss and writes dismissed state when dismiss button is clicked", async () => {
    const user = userEvent.setup();
    const { onDismiss, onStateChange } = renderChecklist();
    await waitFor(() =>
      expect(
        screen.getByLabelText(/Dismiss getting started checklist/i),
      ).toBeInTheDocument(),
    );
    await user.click(
      screen.getByLabelText(/Dismiss getting started checklist/i),
    );
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onStateChange).toHaveBeenCalledWith(
      expect.objectContaining({ dismissed: true }),
    );
  });

  it("shows 'All steps complete!' when all steps are done", async () => {
    mockApi.listDocuments.mockResolvedValue(makeIndexedDocsResponse());
    mockApi.listChatSessions.mockResolvedValue({
      items: [{ session_id: "s1" }],
      total: 1,
      limit: 1,
      offset: 0,
    });
    const state: OnboardingState = {
      ...createDefaultOnboardingState(),
      manuallyCompleted: [
        "invite_team",
        "inspect_citations",
        "review_security",
      ],
    };
    renderChecklist({ state });
    await waitFor(() =>
      expect(screen.getByText("All steps complete!")).toBeInTheDocument(),
    );
  });

  it("shows 'Load sample dataset' button when sample docs are enabled and no docs exist", async () => {
    mockApi.getOnboardingConfig.mockResolvedValue({
      sample_docs_enabled: true,
      reset_at: null,
    });
    mockApi.listDocuments.mockResolvedValue(makeEmptyDocsResponse());
    renderChecklist();
    await waitFor(() =>
      expect(screen.getByText("Load sample dataset")).toBeInTheDocument(),
    );
  });
});
