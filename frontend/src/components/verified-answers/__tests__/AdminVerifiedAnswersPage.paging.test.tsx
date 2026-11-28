import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminVerifiedAnswersPage } from "@/components/verified-answers/AdminVerifiedAnswersPage";
import { createTestQueryClient, renderWithProviders } from "@/test/render";

const mockApi = vi.hoisted(() => ({
  listVerifiedAnswers: vi.fn(),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

vi.mock("@/lib/api/verified-answers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/verified-answers")>()),
  listVerifiedAnswers: (...args: unknown[]) =>
    mockApi.listVerifiedAnswers(...args),
}));

function card(index: number) {
  return {
    answer_id: `va-${index}`,
    title: `Card ${index}`,
    status: "published",
    is_stale: index % 10 === 0,
    expiry_date: null,
    review_date: "2026-01-01",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.listVerifiedAnswers.mockImplementation(
    async (options: { status?: string; limit: number; offset?: number }) => {
      if (options.status !== "published") {
        return { items: [], total: 0, limit: options.limit, offset: 0 };
      }
      const all = Array.from({ length: 70 }, (_, i) => card(i + 1));
      const offset = options.offset ?? 0;
      return {
        items: all.slice(offset, offset + options.limit),
        total: all.length,
        limit: options.limit,
        offset,
      };
    },
  );
});

describe("AdminVerifiedAnswersPage stale tab (R07-06)", () => {
  it("counts the loaded published cards and loads more", async () => {
    renderWithProviders(<AdminVerifiedAnswersPage />, {
      queryClient: createTestQueryClient(),
    });

    await userEvent.click(
      screen.getByRole("tab", { name: "Stale / expiring" }),
    );

    expect(await screen.findByText("Card 50")).toBeInTheDocument();
    expect(screen.getByText("Showing 50 of 70")).toBeInTheDocument();
    expect(screen.queryByText("Card 60")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Card 70")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockApi.listVerifiedAnswers).toHaveBeenCalledWith({
        status: "published",
        limit: 50,
        offset: 50,
      }),
    );
  });
});
