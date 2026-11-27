import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { addBreadcrumb, captureException } = vi.hoisted(() => ({
  addBreadcrumb: vi.fn(),
  captureException: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/lib/observability", () => ({
  addFrontendBreadcrumb: addBreadcrumb,
  captureFrontendException: captureException,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={`/en${href === "/" ? "" : href}`} {...rest}>
      {children}
    </a>
  ),
}));

import RouteErrorFallback, {
  SegmentRouteError,
} from "@/components/errors/RouteErrorFallback";
import arMessages from "@/i18n/messages/ar.json";
import deMessages from "@/i18n/messages/de.json";
import esMessages from "@/i18n/messages/es.json";
import faMessages from "@/i18n/messages/fa.json";
import frMessages from "@/i18n/messages/fr.json";
import { SUPPORTED_LOCALES } from "@/i18n/routing";
import enMessages from "@/i18n/messages/en.json";

const catalogues = {
  de: deMessages,
  es: esMessages,
  fr: frMessages,
  ar: arMessages,
  fa: faMessages,
};

function renderIn(
  locale: "en",
  messages: Record<string, unknown>,
  node: ReactNode,
) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      {node}
    </NextIntlClientProvider>,
  );
}

const error = Object.assign(new Error("boom"), { digest: "abc123" });

beforeEach(() => {
  addBreadcrumb.mockClear();
  captureException.mockClear();
});

describe("RouteErrorFallback", () => {
  it("renders the full-screen page variant with a homepage link", () => {
    const reset = vi.fn();
    renderIn(
      "en",
      enMessages,
      <RouteErrorFallback error={error} reset={reset} />,
    );

    expect(
      screen.getByRole("heading", { name: "Unable to render this page" }),
    ).toBeTruthy();
    expect(screen.getByText("abc123")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Back to homepage" })
        .getAttribute("href"),
    ).toBe("/en");
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("renders the inline segment variant with a dashboard link", () => {
    renderIn(
      "en",
      enMessages,
      <SegmentRouteError error={error} reset={vi.fn()} />,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Back to dashboard" })
        .getAttribute("href"),
    ).toBe("/dashboard");
  });

  it("omits the reference when the error has no digest", () => {
    renderIn(
      "en",
      enMessages,
      <SegmentRouteError error={new Error("x")} reset={vi.fn()} />,
    );
    expect(screen.queryByText(/Error reference/)).toBeNull();
  });

  it("has translated text in every catalogue", () => {
    const keys = [
      "title",
      "description",
      "retry",
      "backToDashboard",
      "backHome",
      "reference",
    ] as const;
    for (const locale of SUPPORTED_LOCALES) {
      const messages = (locale === "en" ? enMessages : catalogues[locale])
        .errors.routeBoundary;
      for (const key of keys) {
        expect(messages[key].trim().length).toBeGreaterThan(0);
        if (locale !== "en") {
          expect(messages[key]).not.toBe(enMessages.errors.routeBoundary[key]);
        }
      }
    }
  });

  it("reports the error with a breadcrumb and a safe digest tag", () => {
    renderIn(
      "en",
      enMessages,
      <SegmentRouteError error={error} reset={vi.fn()} />,
    );

    expect(addBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({ category: "route.error", level: "error" }),
    );
    expect(captureException).toHaveBeenCalledWith(
      error,
      expect.objectContaining({
        feature: "route.render",
        tags: { error_digest: "abc123" },
      }),
    );
  });

  it("tags errors without a digest as unknown", () => {
    renderIn(
      "en",
      enMessages,
      <SegmentRouteError error={new Error("x")} reset={vi.fn()} />,
    );
    expect(captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({ tags: { error_digest: "unknown" } }),
    );
  });
});
