import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";

import { OnboardingChecklist } from "@/components/onboarding/OnboardingChecklist";
import { createDefaultOnboardingState } from "@/lib/onboarding";
import enMessages from "@/i18n/messages/en.json";

const mockApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/api/onboarding", () => ({
  getOnboardingConfig: () =>
    Promise.resolve({ sample_docs_enabled: false, reset_at: null }),
  loadSampleDataset: vi.fn(),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (options: unknown) => mockApi.listDocuments(options),
}));

vi.mock("@/lib/api/chat", () => ({
  listChatSessions: () =>
    Promise.resolve({ items: [], total: 0, limit: 1, offset: 0 }),
}));

vi.mock("@/lib/analytics", () => ({
  trackOnboardingEvent: vi.fn().mockResolvedValue(undefined),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("OnboardingChecklist document counts (R07-06)", () => {
  it("asks for one-row pages with totals instead of 200 rows", async () => {
    // 500 documents, the indexed one far beyond the first 200 rows.
    mockApi.listDocuments.mockImplementation(
      async (options: { status?: string }) => ({
        items: [],
        total: options.status === "indexed" ? 1 : 500,
        limit: 1,
        offset: 0,
      }),
    );

    render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <OnboardingChecklist
            session={{
              userId: "user-1",
              email: "owner@example.com",
              role: "owner",
              organizationId: "org-1",
              organizationName: "Test Org",
            }}
            state={createDefaultOnboardingState()}
            onStateChange={vi.fn()}
            onDismiss={vi.fn()}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>,
    );

    await waitFor(() =>
      expect(mockApi.listDocuments).toHaveBeenCalledWith({
        limit: 1,
        status: "indexed",
        include_total: true,
      }),
    );
    expect(mockApi.listDocuments).toHaveBeenCalledWith({
      limit: 1,
      include_total: true,
    });
    await waitFor(() => {
      const uploadItem = screen
        .getByText("Upload your first document")
        .closest("li");
      expect(uploadItem?.textContent).toContain("(complete)");
    });
  });
});
