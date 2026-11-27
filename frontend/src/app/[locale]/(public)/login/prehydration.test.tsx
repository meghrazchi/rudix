import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as authLogin from "@/lib/auth-login";

const mockState = vi.hoisted(() => ({
  replace: vi.fn(),
  setAuthenticatedSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockState.replace, push: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => (key === "next" ? "/documents" : null),
  }),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: { status: "unauthenticated", session: null },
    setAuthenticatedSession: mockState.setAuthenticatedSession,
    signOut: vi.fn(),
    boundaryMessage: null,
    clearBoundaryEvent: vi.fn(),
  }),
}));

import LoginPage from "./page";

let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("LoginPage before hydration (R07-01)", () => {
  it("keeps credentials typed into the server-rendered form", async () => {
    vi.spyOn(authLogin, "getSsoStartHref").mockReturnValue(null);
    vi.spyOn(authLogin, "getForgotPasswordHref").mockReturnValue(null);
    const startSpy = vi
      .spyOn(authLogin, "startLoginSession")
      .mockResolvedValue({
        userId: "user-1",
        email: "user@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      });

    const container = document.createElement("div");
    container.innerHTML = renderToString(<LoginPage />);
    document.body.appendChild(container);

    // A visitor types before React has hydrated the page.
    (container.querySelector('input[type="email"]') as HTMLInputElement).value =
      "user@example.com";
    (
      container.querySelector('input[type="password"]') as HTMLInputElement
    ).value = "password123";

    await act(async () => {
      root = hydrateRoot(container, <LoginPage />);
    });

    expect(screen.getByLabelText("Email")).toHaveValue("user@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(startSpy).toHaveBeenCalledWith({
        email: "user@example.com",
        password: "password123",
      }),
    );
  });
});
