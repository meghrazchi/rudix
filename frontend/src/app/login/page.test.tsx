import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";
import * as authLogin from "@/lib/auth-login";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  nextPath: "/documents",
  reason: null as string | null,
  boundaryMessage: null as string | null,
  authState: { status: "unauthenticated", session: null } as SessionState,
  setAuthenticatedSession: vi.fn(),
  clearBoundaryEvent: vi.fn(),
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
      if (key === "reason") {
        return mockState.reason;
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
    boundaryMessage: mockState.boundaryMessage,
    clearBoundaryEvent: mockState.clearBoundaryEvent,
  }),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    mockState.replace.mockReset();
    mockState.push.mockReset();
    mockState.setAuthenticatedSession.mockReset();
    mockState.clearBoundaryEvent.mockReset();
    mockState.nextPath = "/documents";
    mockState.reason = null;
    mockState.boundaryMessage = null;
    mockState.authState = { status: "unauthenticated", session: null };

    vi.spyOn(authLogin, "getAuthClientConfig").mockReturnValue({
      providerName: null,
      loginUrl: null,
      ssoUrl: null,
      forgotPasswordUrl: null,
      localFallbackEnabled: true,
      localFallbackPassword: null,
      defaultOrganizationId: "demo-org-001",
      defaultOrganizationName: "Demo Organization",
      defaultRole: "member",
      defaultUserId: "demo-user-001",
      defaultAccessToken: null,
      defaultRefreshToken: null,
    });
    vi.spyOn(authLogin, "getSsoStartHref").mockReturnValue(null);
    vi.spyOn(authLogin, "getForgotPasswordHref").mockReturnValue(null);
    vi.spyOn(authLogin, "getLoginProviderLabel").mockReturnValue("SSO");
  });

  it("shows validation errors when email/password are invalid", async () => {
    const startSpy = vi.spyOn(authLogin, "startLoginSession");
    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("Email"), "invalid-email");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByText("Enter a valid email address"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Password must be at least 8 characters"),
    ).toBeInTheDocument();
    expect(startSpy).not.toHaveBeenCalled();
  });

  it("submits valid credentials and redirects to requested page", async () => {
    const session = {
      userId: "user-1",
      email: "user@example.com",
      role: "member" as const,
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    };

    vi.spyOn(authLogin, "startLoginSession").mockResolvedValueOnce(session);

    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(authLogin.startLoginSession).toHaveBeenCalledWith({
        email: "user@example.com",
        password: "password123",
      });
    });
    expect(mockState.setAuthenticatedSession).toHaveBeenCalledWith(session);
    expect(mockState.replace).toHaveBeenCalledWith("/documents");
  });

  it("shows safe error message for failed sign-in", async () => {
    vi.spyOn(authLogin, "startLoginSession").mockRejectedValueOnce(
      new authLogin.LoginFlowError(
        "invalid_credentials",
        "Invalid email or password.",
      ),
    );

    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid email or password.",
    );
  });

  it("redirects authenticated users away from login", async () => {
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

    render(<LoginPage />);

    await waitFor(() => {
      expect(mockState.replace).toHaveBeenCalledWith("/documents");
    });
  });

  it("redirects authenticated users without organization to onboarding", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "new@example.com",
        role: "member",
        organizationId: null,
        organizationName: null,
        accessToken: "token-2",
      },
    };

    render(<LoginPage />);

    await waitFor(() => {
      expect(mockState.replace).toHaveBeenCalledWith(
        "/organization-onboarding",
      );
    });
  });

  it("is keyboard accessible with labels and tab flow", async () => {
    render(<LoginPage />);

    const emailInput = screen.getByLabelText("Email");
    const passwordInput = screen.getByLabelText("Password");
    const submitButton = screen.getByRole("button", { name: "Sign in" });

    expect(emailInput).toBeInTheDocument();
    expect(passwordInput).toBeInTheDocument();
    expect(submitButton).toBeInTheDocument();

    await userEvent.tab();
    expect(emailInput).toHaveFocus();

    await userEvent.tab();
    expect(passwordInput).toHaveFocus();

    for (
      let attempts = 0;
      attempts < 10 && document.activeElement !== submitButton;
      attempts += 1
    ) {
      await userEvent.tab();
    }
    expect(submitButton).toHaveFocus();
  });

  it("shows session-expired notice from login reason query", async () => {
    mockState.reason = "session_expired";
    render(<LoginPage />);

    expect(
      await screen.findByText("Your session expired. Sign in again."),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(mockState.clearBoundaryEvent).toHaveBeenCalled();
    });
  });
});
