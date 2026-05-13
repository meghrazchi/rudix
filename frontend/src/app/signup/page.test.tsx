import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SignupPage from "@/app/signup/page";
import * as authSignup from "@/lib/auth-signup";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  nextPath: "/documents",
  authState: { status: "unauthenticated", session: null } as SessionState,
  setAuthenticatedSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: mockState.replace,
    push: mockState.push,
  }),
  useSearchParams: () => ({
    get: (key: string) => {
      if (key === "next") {
        return mockState.nextPath;
      }
      return null;
    },
  }),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: mockState.setAuthenticatedSession,
    signOut: vi.fn(),
  }),
}));

describe("SignupPage", () => {
  beforeEach(() => {
    mockState.replace.mockReset();
    mockState.push.mockReset();
    mockState.setAuthenticatedSession.mockReset();
    mockState.nextPath = "/documents";
    mockState.authState = { status: "unauthenticated", session: null };

    vi.spyOn(authSignup, "getSignupSsoStartHref").mockReturnValue(null);
    vi.spyOn(authSignup, "getSignupProviderLabel").mockReturnValue("SSO");
  });

  it("shows inline validation errors for invalid input and missing terms", async () => {
    const startSpy = vi.spyOn(authSignup, "startSignupSession");
    render(<SignupPage />);

    await userEvent.type(screen.getByLabelText("Full name"), "A");
    await userEvent.type(screen.getByLabelText("Email"), "bad-email");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Full name must be at least 2 characters")).toBeInTheDocument();
    expect(screen.getByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText("Password must be at least 8 characters")).toBeInTheDocument();
    expect(screen.getByText("Workspace name must be at least 2 characters")).toBeInTheDocument();
    expect(screen.getByText("You must accept the terms to create an account")).toBeInTheDocument();
    expect(startSpy).not.toHaveBeenCalled();
  });

  it("redirects to organization onboarding after successful signup when backend requires onboarding", async () => {
    vi.spyOn(authSignup, "startSignupSession").mockResolvedValueOnce({
      session: {
        userId: "user-1",
        email: "user@example.com",
        role: "member",
        organizationId: null,
        organizationName: null,
        accessToken: "token-1",
      },
      nextStep: "onboarding",
    });

    render(<SignupPage />);

    await userEvent.type(screen.getByLabelText("Full name"), "Jane Doe");
    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.type(screen.getByLabelText("Workspace name"), "Acme Workspace");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(authSignup.startSignupSession).toHaveBeenCalledWith({
        fullName: "Jane Doe",
        email: "user@example.com",
        password: "password123",
        workspaceMode: "create",
        workspaceName: "Acme Workspace",
        inviteCode: "",
        acceptTerms: true,
      });
    });

    expect(mockState.setAuthenticatedSession).toHaveBeenCalled();
    expect(mockState.replace).toHaveBeenCalledWith("/organization-onboarding");
  });

  it("shows safe duplicate-email error", async () => {
    vi.spyOn(authSignup, "startSignupSession").mockRejectedValueOnce(
      new authSignup.SignupFlowError("duplicate_email", "An account with this email already exists."),
    );

    render(<SignupPage />);

    await userEvent.type(screen.getByLabelText("Full name"), "Jane Doe");
    await userEvent.type(screen.getByLabelText("Email"), "existing@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.type(screen.getByLabelText("Workspace name"), "Acme Workspace");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An account with this email already exists.",
    );
  });

  it("redirects authenticated users away from signup", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "user@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };

    render(<SignupPage />);

    await waitFor(() => {
      expect(mockState.replace).toHaveBeenCalledWith("/documents");
    });
  });
});
