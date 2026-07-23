import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  GlobalReportFilters,
  ReportFiltersProvider,
} from "@/components/reports/ReportFilters";

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  searchParams: new URLSearchParams("date=7d"),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/reports",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.searchParams,
}));

vi.mock("@/lib/api/connectors", () => ({
  listConnectorConnections: vi.fn().mockResolvedValue({
    total: 1,
    items: [{ id: "connector-1", display_name: "Engineering Drive" }],
  }),
}));

function renderFilters() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReportFiltersProvider>
        <GlobalReportFilters />
      </ReportFiltersProvider>
    </QueryClientProvider>,
  );
}

describe("GlobalReportFilters", () => {
  it("updates and resets URL-backed filters", async () => {
    navigation.replace.mockClear();
    renderFilters();

    fireEvent.change(screen.getByLabelText("Confidence"), {
      target: { value: "low" },
    });
    expect(navigation.replace).toHaveBeenCalledWith(
      "/reports?date=7d&confidence=low",
      { scroll: false },
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(navigation.replace).toHaveBeenCalledWith("/reports", {
      scroll: false,
    });

    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "Engineering Drive" }),
      ).toBeInTheDocument(),
    );
  });
});
