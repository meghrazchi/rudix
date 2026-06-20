import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

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

vi.mock("@/components/public/PublicMarketingLayout", () => ({
  PublicMarketingLayout: ({ children }: { children: ReactNode }) => (
    <>{children}</>
  ),
}));

import ChangelogRoutePage, { metadata } from "./page";

describe("Changelog public page", () => {
  it("renders current and historical release notes", () => {
    render(<ChangelogRoutePage />);

    expect(
      screen.getByRole("heading", {
        name: "Release notes for product improvements, fixes, and breaking changes",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Current and historical release notes",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "v0.7.0" }).length,
    ).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("heading", { name: "v0.6.0" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "v0.5.0" })).toBeInTheDocument();
    expect(screen.getAllByText("Added").length).toBeGreaterThanOrEqual(3);
    expect(
      screen.getByRole("link", { name: "Review security disclosure" }),
    ).toHaveAttribute("href", "/legal/security-disclosure");
    expect(
      screen
        .getAllByRole("link", { name: "Contact the team" })
        .some((link) => link.getAttribute("href") === "/contact"),
    ).toBe(true);
  });

  it("defines unique SEO metadata for /changelog", () => {
    expect(metadata.title).toBe("Changelog | Rudix");
    expect(metadata.description).toBe(
      "Browse public Rudix release notes, product improvements, fixes, and safe links to supporting documentation.",
    );
    expect(metadata.alternates?.canonical).toBe("/changelog");
  });
});
