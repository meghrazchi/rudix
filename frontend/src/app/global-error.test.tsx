import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { addBreadcrumb, captureException } = vi.hoisted(() => ({
  addBreadcrumb: vi.fn(),
  captureException: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/lib/observability", () => ({
  addFrontendBreadcrumb: addBreadcrumb,
  captureFrontendException: captureException,
}));
vi.mock("@/app/globals.css", () => ({}));

import GlobalError from "./global-error";

const error = Object.assign(new Error("boom"), { digest: "d1" });

beforeEach(() => {
  addBreadcrumb.mockClear();
  captureException.mockClear();
  document.documentElement.lang = "";
  document.cookie = "NEXT_LOCALE=; Max-Age=0; path=/";
});

describe("GlobalError", () => {
  it("renders English by default and reports the error", () => {
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />, {
      container: document.documentElement,
    });

    expect(
      screen.getByRole("heading", { name: "Unable to render this page" }),
    ).toBeTruthy();
    expect(screen.getByText("d1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Back to homepage" })).toBeTruthy();
    expect(addBreadcrumb).toHaveBeenCalledTimes(1);
    expect(captureException).toHaveBeenCalledTimes(1);
  });

  it("uses the cookie locale and right-to-left direction", () => {
    document.cookie = "NEXT_LOCALE=fa; path=/";
    render(<GlobalError error={new Error("x")} reset={vi.fn()} />, {
      container: document.documentElement,
    });

    expect(screen.getByText("تلاش دوباره")).toBeTruthy();
    expect(screen.queryByText(/شناسه خطا/)).toBeNull();
  });
});
