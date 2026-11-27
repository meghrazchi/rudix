import { beforeEach, describe, expect, it, vi } from "vitest";

const { redirectMock } = vi.hoisted(() => ({
  redirectMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
}));

import SignupAliasPage from "./page";

describe("Signup alias public route", () => {
  beforeEach(() => {
    redirectMock.mockReset();
  });

  it("redirects /signup to /login because self-registration is disabled", () => {
    SignupAliasPage();
    expect(redirectMock).toHaveBeenCalledWith("/login");
  });
});
