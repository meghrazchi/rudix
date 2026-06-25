import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminOnboardingPage } from "@/components/admin/AdminOnboardingPage";
import type { OnboardingConfig } from "@/lib/api/onboarding";

const mockApi = vi.hoisted(() => ({
  getOnboardingConfig: vi.fn(),
  patchOnboardingConfig: vi.fn(),
  resetOnboarding: vi.fn(),
}));

vi.mock("@/lib/api/onboarding", () => ({
  getOnboardingConfig: () => mockApi.getOnboardingConfig(),
  patchOnboardingConfig: (data: Partial<OnboardingConfig>) =>
    mockApi.patchOnboardingConfig(data),
  resetOnboarding: () => mockApi.resetOnboarding(),
}));

function makeConfig(
  overrides: Partial<OnboardingConfig> = {},
): OnboardingConfig {
  return {
    sample_docs_enabled: false,
    reset_at: null,
    ...overrides,
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage() {
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <AdminOnboardingPage />
    </QueryClientProvider>,
  );
  return qc;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("AdminOnboardingPage", () => {
  it("shows loading state while config is fetching", () => {
    mockApi.getOnboardingConfig.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the onboarding settings page after config loads", async () => {
    mockApi.getOnboardingConfig.mockResolvedValue(makeConfig());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Onboarding Settings")).toBeInTheDocument(),
    );
    expect(screen.getByText("Sample dataset")).toBeInTheDocument();
    expect(screen.getByText("Reset onboarding")).toBeInTheDocument();
  });

  it("shows sample docs toggle as disabled when feature is off", async () => {
    mockApi.getOnboardingConfig.mockResolvedValue(
      makeConfig({ sample_docs_enabled: false }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Onboarding Settings")).toBeInTheDocument(),
    );
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });

  it("shows sample docs toggle as enabled when feature is on", async () => {
    mockApi.getOnboardingConfig.mockResolvedValue(
      makeConfig({ sample_docs_enabled: true }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("switch")).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("can toggle sample docs enabled via PATCH", async () => {
    const user = userEvent.setup();
    mockApi.getOnboardingConfig.mockResolvedValue(
      makeConfig({ sample_docs_enabled: false }),
    );
    mockApi.patchOnboardingConfig.mockResolvedValue(
      makeConfig({ sample_docs_enabled: true }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    await user.click(screen.getByRole("switch"));
    expect(mockApi.patchOnboardingConfig).toHaveBeenCalledWith({
      sample_docs_enabled: true,
    });
  });

  it("shows last reset time when reset_at is set", async () => {
    mockApi.getOnboardingConfig.mockResolvedValue(
      makeConfig({ reset_at: "2026-06-25T10:00:00.000Z" }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Last reset:/i)).toBeInTheDocument(),
    );
  });

  it("calls resetOnboarding after confirm and shows success", async () => {
    const user = userEvent.setup();
    mockApi.getOnboardingConfig.mockResolvedValue(makeConfig());
    mockApi.resetOnboarding.mockResolvedValue(
      makeConfig({ reset_at: "2026-06-25T12:00:00.000Z" }),
    );
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Reset onboarding for all users/i }),
      ).toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", { name: /Reset onboarding for all users/i }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Onboarding reset successfully/i),
      ).toBeInTheDocument(),
    );
    expect(mockApi.resetOnboarding).toHaveBeenCalledTimes(1);
  });
});
