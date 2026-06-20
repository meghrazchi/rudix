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
});
