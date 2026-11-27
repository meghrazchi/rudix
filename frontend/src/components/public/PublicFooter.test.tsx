import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { PublicFooter } from "@/components/public/PublicFooter";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

vi.mock("@/components/public/PublicActionLink", () => ({
  PublicActionLink: ({
    href,
    children,
    className,
    ariaLabel,
    onClick,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
    ariaLabel?: string;
    onClick?: () => void;
  }) => (
    <a
      href={href}
      className={className}
      aria-label={ariaLabel}
      onClick={onClick}
    >
      {children}
    </a>
  ),
}));

vi.mock("@/components/i18n/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher" />,
}));

describe("PublicFooter", () => {
  it("renders the public changelog link in the product group", () => {
    render(<PublicFooter links={resolvePublicSiteLinks()} />);

    expect(screen.getByTestId("language-switcher")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Changelog" })).toHaveAttribute(
      "href",
      "/changelog",
    );
  });

  it("links every legal page, including the DPA and subprocessors", () => {
    render(<PublicFooter links={resolvePublicSiteLinks()} />);

    for (const [name, href] of [
      ["Privacy Policy", "/legal/privacy"],
      ["Terms of Service", "/legal/terms"],
      ["Cookie Policy", "/legal/cookies"],
      ["DPA", "/legal/dpa"],
      ["Subprocessors", "/legal/subprocessors"],
      ["Acceptable Use", "/legal/acceptable-use"],
      ["Security Disclosure", "/legal/security-disclosure"],
    ]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });

  it("lists solution pages and leaves signed-in app links out", () => {
    render(<PublicFooter links={resolvePublicSiteLinks()} />);

    expect(screen.getByRole("link", { name: "All Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByRole("link", { name: "HR" })).toHaveAttribute(
      "href",
      "/solutions/hr",
    );
    expect(
      screen.queryByRole("link", { name: "Pipeline Explorer" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/RAG/)).not.toBeInTheDocument();
  });
});
