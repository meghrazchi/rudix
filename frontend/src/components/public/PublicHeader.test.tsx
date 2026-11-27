import { fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isActiveNavHref,
  PublicHeader,
} from "@/components/public/PublicHeader";
import enMessages from "@/i18n/messages/en.json";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const pathnameMock = vi.fn(() => "/");

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => pathnameMock(),
}));

vi.mock("@/components/public/PublicActionLink", () => ({
  PUBLIC_FOCUS_RING_CLASS: "",
  PublicActionLink: ({
    href,
    children,
    className,
    ariaLabel,
    ariaCurrent,
    onClick,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
    ariaLabel?: string;
    ariaCurrent?: "page";
    onClick?: () => void;
  }) => (
    <a
      href={href}
      className={className}
      aria-label={ariaLabel}
      aria-current={ariaCurrent}
      onClick={onClick}
    >
      {children}
    </a>
  ),
}));

vi.mock("@/components/i18n/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher" />,
}));

function renderHeader() {
  return render(
    <NextIntlClientProvider locale="en" messages={enMessages}>
      <PublicHeader links={resolvePublicSiteLinks()} />
    </NextIntlClientProvider>,
  );
}

describe("isActiveNavHref", () => {
  it("matches the page itself and its sub-pages only", () => {
    expect(isActiveNavHref("/solutions", "/solutions")).toBe(true);
    expect(isActiveNavHref("/solutions/hr", "/solutions")).toBe(true);
    expect(isActiveNavHref("/solutions-extra", "/solutions")).toBe(false);
    expect(isActiveNavHref("/pricing", "/solutions")).toBe(false);
    expect(isActiveNavHref("/", "/")).toBe(false);
    expect(isActiveNavHref("/docs", "https://docs.example.com")).toBe(false);
  });
});

describe("PublicHeader", () => {
  beforeEach(() => {
    pathnameMock.mockReturnValue("/");
  });

  it("keeps the primary nav to four items plus login and demo", () => {
    renderHeader();
    const nav = screen.getByRole("navigation", { name: "Primary navigation" });

    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Product", "Solutions", "Security", "Pricing"]);
    expect(screen.getByRole("link", { name: "Login" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Request Demo" }),
    ).toBeInTheDocument();
  });

  it("marks the current section, including sub-pages, with aria-current", () => {
    pathnameMock.mockReturnValue("/solutions/hr");
    renderHeader();
    const nav = screen.getByRole("navigation", { name: "Primary navigation" });

    expect(
      within(nav).getByRole("link", { name: "Solutions" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(nav).getByRole("link", { name: "Pricing" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("marks the current page in the mobile menu", () => {
    pathnameMock.mockReturnValue("/pricing");
    renderHeader();
    fireEvent.click(
      screen.getByRole("button", { name: "Open navigation menu" }),
    );
    const mobileNav = screen.getByRole("navigation", {
      name: "Mobile navigation",
    });

    expect(
      within(mobileNav).getByRole("link", { name: "Pricing" }),
    ).toHaveAttribute("aria-current", "page");
  });
});
