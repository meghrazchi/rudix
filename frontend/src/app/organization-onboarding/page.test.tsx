import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrganizationOnboardingPage from "@/app/organization-onboarding/page";
import {
  OrganizationOnboardingError,
  type OrganizationOnboardingFormValues,
} from "@/lib/organization-onboarding";
import type { SessionState } from "@/lib/auth-session";
import * as onboardingLib from "@/lib/organization-onboarding";

const mockState = vi.hoisted(() => ({
  replace: vi.fn(),
  authState: { status: "unauthenticated", session: null } as SessionState,
  setAuthenticatedSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: mockState.replace,
  }),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: mockState.setAuthenticatedSession,
    signOut: vi.fn(),
  }),
}));

function authenticatedNoOrganizationState(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "owner@example.com",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: "token-1",
    },
  };
}

describe("OrganizationOnboardingPage", () => {
  beforeEach(() => {
    mockState.replace.mockReset();
    mockState.setAuthenticatedSession.mockReset();
    mockState.authState = authenticatedNoOrganizationState();

    vi.spyOn(onboardingLib, "loadOrganizationOnboardingDraft").mockResolvedValue(null);
    vi.spyOn(onboardingLib, "persistOrganizationOnboardingDraft").mockResolvedValue();
    vi.spyOn(onboardingLib, "clearOnboardingDraft").mockImplementation(() => undefined);
    vi.spyOn(onboardingLib, "completeOrganizationOnboarding").mockResolvedValue({
      organizationId: "org-acme-workspace",
      organizationName: "Acme Workspace",
      role: "admin",
    });
  });

  it("redirects unauthenticated users to login with next path", async () => {
    mockState.authState = { status: "unauthenticated", session: null };
    render(<OrganizationOnboardingPage />);

    await waitFor(() => {
      expect(mockState.replace).toHaveBeenCalledWith("/login?next=%2Forganization-onboarding");
    });
  });

  it("redirects already-onboarded users to dashboard", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "owner@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };

    render(<OrganizationOnboardingPage />);

    await waitFor(() => {
      expect(mockState.replace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("shows validation error when workspace name is missing before advancing", async () => {
    render(<OrganizationOnboardingPage />);

    expect(
      await screen.findByRole("heading", { name: "Organization onboarding" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(
      await screen.findByText("Workspace name must be at least 2 characters"),
    ).toBeInTheDocument();
  });

  it("completes onboarding and redirects to dashboard", async () => {
    render(<OrganizationOnboardingPage />);

    await screen.findByRole("heading", { name: "Organization onboarding" });

    await userEvent.type(screen.getByLabelText("Workspace name"), "Acme Workspace");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Complete setup" }));

    await waitFor(() => {
      expect(onboardingLib.completeOrganizationOnboarding).toHaveBeenCalledWith({
        workspaceName: "Acme Workspace",
        domainAllowlistText: "",
        defaultAccessRole: "member",
        allowSelfServeJoin: true,
        invites: [{ email: "", role: "member" }],
      } satisfies OrganizationOnboardingFormValues);
    });

    expect(mockState.setAuthenticatedSession).toHaveBeenCalledWith({
      userId: "user-1",
      email: "owner@example.com",
      role: "admin",
      organizationId: "org-acme-workspace",
      organizationName: "Acme Workspace",
      accessToken: "token-1",
    });
    expect(mockState.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("shows safe completion errors without clearing entered values", async () => {
    vi.spyOn(onboardingLib, "completeOrganizationOnboarding").mockRejectedValueOnce(
      new OrganizationOnboardingError(
        "workspace_conflict",
        "Workspace name is already in use. Choose another name.",
      ),
    );

    render(<OrganizationOnboardingPage />);

    await screen.findByRole("heading", { name: "Organization onboarding" });

    await userEvent.type(screen.getByLabelText("Workspace name"), "Acme Workspace");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Complete setup" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Workspace name is already in use. Choose another name.",
    );
    expect(screen.getByText("Acme Workspace")).toBeInTheDocument();
  });
});
