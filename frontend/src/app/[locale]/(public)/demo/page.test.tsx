import { beforeEach, describe, expect, it, vi } from "vitest";

const { redirectMock } = vi.hoisted(() => ({
  redirectMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
}));

import DemoAliasPage from "./page";

describe("Demo alias public route", () => {
  beforeEach(() => {
    redirectMock.mockReset();
  });

  it("redirects /demo to /contact", () => {
    DemoAliasPage();
    expect(redirectMock).toHaveBeenCalledWith("/contact");
  });
});
