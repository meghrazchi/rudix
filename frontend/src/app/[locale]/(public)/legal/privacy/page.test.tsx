import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyPage from "./page";

describe("Privacy Policy page", () => {
  it("renders the page heading", () => {
    render(<PrivacyPage />);
    expect(
      screen.getByRole("heading", { name: /privacy policy/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<PrivacyPage />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("renders key privacy sections", () => {
    render(<PrivacyPage />);
    expect(
      screen.getByRole("region", { name: /information we collect/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /how we use your information/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /ai model providers/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /data retention and deletion/i }),
    ).toBeInTheDocument();
  });

  it("links to the subprocessors page", () => {
    render(<PrivacyPage />);
    expect(
      screen.getByRole("link", { name: /subprocessors page/i }),
    ).toHaveAttribute("href", "/legal/subprocessors");
  });

  it("links to the cookie policy", () => {
    render(<PrivacyPage />);
    expect(
      screen.getByRole("link", { name: /cookie policy/i }),
    ).toHaveAttribute("href", "/legal/cookies");
  });

  it("renders the public header and footer", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
