import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { NotFoundPage } from "@/components/public/pages/NotFoundPage";
import enMessages from "@/i18n/messages/en.json";

vi.mock("@/components/public/PublicMarketingLayout", () => ({
  PublicMarketingLayout: ({
    children,
    theme,
  }: {
    children: React.ReactNode;
    theme?: string;
  }) => (
    <div data-testid="layout" data-theme={theme}>
      {children}
    </div>
  ),
}));

describe("NotFoundPage", () => {
  it("renders the redesigned 404 with recovery links in the system theme", () => {
    render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <NotFoundPage />
      </NextIntlClientProvider>,
    );

    expect(screen.getByTestId("layout")).toHaveAttribute(
      "data-theme",
      "system",
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Page not found" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Error 404")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to homepage" }),
    ).toHaveAttribute("href", expect.stringMatching(/\/$/));
    expect(screen.getByRole("link", { name: "Contact us" })).toHaveAttribute(
      "href",
      expect.stringContaining("/contact"),
    );
  });
});
