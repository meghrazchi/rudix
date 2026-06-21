import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFreshnessThresholdPage } from "@/components/admin/AdminFreshnessThresholdPage";
import { ApiClientError } from "@/lib/api/errors";
import type { FreshnessThresholdsResponse } from "@/lib/api/freshness-thresholds";

const mockApi = vi.hoisted(() => ({
  getFreshnessThresholds: vi.fn(),
  patchFreshnessThresholds: vi.fn(),
}));

vi.mock("@/lib/api/freshness-thresholds", () => ({
  getFreshnessThresholds: mockApi.getFreshnessThresholds,
  patchFreshnessThresholds: mockApi.patchFreshnessThresholds,
}));

const defaultPolicy: FreshnessThresholdsResponse = {
  organization_id: "org-1",
  warn_stale_after_days: null,
  warn_unreviewed_after_days: null,
  auto_exclude_deprecated: true,
  auto_exclude_expired: true,
  label: null,
  updated_at: null,
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = makeClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderPage() {
  return render(<AdminFreshnessThresholdPage />, { wrapper: Wrapper });
}

describe("AdminFreshnessThresholdPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state before data arrives", () => {
    mockApi.getFreshnessThresholds.mockResolvedValue(
      new Promise(() => {}), // never resolves
    );
    renderPage();
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("renders form after data loads", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("freshness-threshold-form")).toBeTruthy(),
    );
  });

  it("shows forbidden state on 403", async () => {
    mockApi.getFreshnessThresholds.mockRejectedValue(
      new ApiClientError("Forbidden", 403),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/forbidden|access denied/i)).toBeTruthy(),
    );
  });

  it("shows error state on generic failure", async () => {
    mockApi.getFreshnessThresholds.mockRejectedValue(
      new Error("network error"),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });

  it("displays 'No overrides set' when updated_at is null", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no overrides set/i)).toBeTruthy(),
    );
  });

  it("displays last updated date when updated_at is set", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue({
      ...defaultPolicy,
      updated_at: "2026-05-01T10:00:00Z",
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/last updated/i)).toBeTruthy());
  });

  it("save button is disabled when form has not changed", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("save-freshness-thresholds")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("save-freshness-thresholds").closest("button"),
    ).toBeDisabled();
  });

  it("save button enables after changing stale days input", async () => {
    const user = userEvent.setup();
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() => screen.getByLabelText(/warn stale after/i));
    const input = screen.getByLabelText(/warn stale after/i);
    await user.clear(input);
    await user.type(input, "60");
    expect(
      screen.getByTestId("save-freshness-thresholds").closest("button"),
    ).not.toBeDisabled();
  });

  it("calls patchFreshnessThresholds on save", async () => {
    const user = userEvent.setup();
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    mockApi.patchFreshnessThresholds.mockResolvedValue({
      ...defaultPolicy,
      warn_stale_after_days: 60,
      updated_at: "2026-06-27T10:00:00Z",
    });
    renderPage();
    await waitFor(() => screen.getByLabelText(/warn stale after/i));
    const input = screen.getByLabelText(/warn stale after/i);
    await user.clear(input);
    await user.type(input, "60");
    await user.click(screen.getByTestId("save-freshness-thresholds"));
    await waitFor(() =>
      expect(mockApi.patchFreshnessThresholds).toHaveBeenCalledWith(
        expect.objectContaining({ warn_stale_after_days: 60 }),
      ),
    );
  });

  it("shows success message after save", async () => {
    const user = userEvent.setup();
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    mockApi.patchFreshnessThresholds.mockResolvedValue({
      ...defaultPolicy,
      warn_stale_after_days: 30,
      updated_at: "2026-06-27T10:00:00Z",
    });
    renderPage();
    await waitFor(() => screen.getByLabelText(/warn stale after/i));
    await user.type(screen.getByLabelText(/warn stale after/i), "30");
    await user.click(screen.getByTestId("save-freshness-thresholds"));
    await waitFor(() => expect(screen.getByRole("status")).toBeTruthy());
  });

  it("shows error message on save failure", async () => {
    const user = userEvent.setup();
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    mockApi.patchFreshnessThresholds.mockRejectedValue(
      new Error("server error"),
    );
    renderPage();
    await waitFor(() => screen.getByLabelText(/warn stale after/i));
    await user.type(screen.getByLabelText(/warn stale after/i), "45");
    await user.click(screen.getByTestId("save-freshness-thresholds"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });

  it("renders auto_exclude_deprecated toggle as checked by default", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByRole("switch", { name: /exclude deprecated/i }),
      ).toBeTruthy(),
    );
    const toggle = screen.getByRole("switch", { name: /exclude deprecated/i });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("toggling exclude_deprecated changes its aria-checked", async () => {
    const user = userEvent.setup();
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() =>
      screen.getByRole("switch", { name: /exclude deprecated/i }),
    );
    const toggle = screen.getByRole("switch", { name: /exclude deprecated/i });
    await user.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  it("renders unreviewed days input", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue({
      ...defaultPolicy,
      warn_unreviewed_after_days: 120,
    });
    renderPage();
    await waitFor(() => screen.getByLabelText(/warn unreviewed after/i));
    const input = screen.getByLabelText(
      /warn unreviewed after/i,
    ) as HTMLInputElement;
    expect(input.value).toBe("120");
  });

  it("heading and description are present", async () => {
    mockApi.getFreshnessThresholds.mockResolvedValue(defaultPolicy);
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /freshness thresholds/i }),
      ).toBeTruthy(),
    );
    expect(
      screen.getByText(/configure when answer trust panels/i),
    ).toBeTruthy();
  });
});
