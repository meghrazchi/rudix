import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { CookiePreferencesModal } from "@/components/consent/CookiePreferencesModal";
import { createDefaultConsentDecisions, type ConsentDecisions } from "@/lib/consent";
import { renderWithProviders } from "@/test/render";

function renderModal(
  overrides: {
    isOpen?: boolean;
    decisions?: ConsentDecisions;
    onClose?: () => void;
    onAcceptAll?: () => void;
    onRejectNonEssential?: () => void;
    onSave?: (d: Partial<ConsentDecisions>) => void;
  } = {},
) {
  const props = {
    isOpen: true,
    decisions: createDefaultConsentDecisions(),
    onClose: vi.fn(),
    onAcceptAll: vi.fn(),
    onRejectNonEssential: vi.fn(),
    onSave: vi.fn(),
    ...overrides,
  };
  return {
    ...renderWithProviders(<CookiePreferencesModal {...props} />),
    props,
  };
}

describe("CookiePreferencesModal", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the modal when isOpen is true", () => {
    renderModal();
    expect(
      screen.getByRole("dialog", { name: /cookie preferences/i }),
    ).toBeInTheDocument();
  });

  it("does not render when isOpen is false", () => {
    renderModal({ isOpen: false });
    expect(
      screen.queryByRole("dialog", { name: /cookie preferences/i }),
    ).not.toBeInTheDocument();
  });

  it("shows necessary category as always on and disabled", () => {
    renderModal();
    const necessaryToggle = screen.getByRole("switch", {
      name: /necessary/i,
    });
    expect(necessaryToggle).toBeDisabled();
    expect(necessaryToggle).toHaveAttribute("aria-checked", "true");
  });

  it("shows functional category as a toggleable switch", () => {
    renderModal({ decisions: { functional: true, analytics: false } });
    const toggle = screen.getByRole("switch", { name: /functional/i });
    expect(toggle).not.toBeDisabled();
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("toggles functional category on click", () => {
    renderModal({ decisions: { functional: false, analytics: false } });
    const toggle = screen.getByRole("switch", { name: /functional/i });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("calls onSave with current local decisions when Save Preferences is clicked", () => {
    const onSave = vi.fn();
    renderModal({
      decisions: { functional: false, analytics: false },
      onSave,
    });
    const functionalToggle = screen.getByRole("switch", {
      name: /functional/i,
    });
    fireEvent.click(functionalToggle);
    fireEvent.click(screen.getByRole("button", { name: /save preferences/i }));
    expect(onSave).toHaveBeenCalledWith({ functional: true, analytics: false });
  });

  it("calls onAcceptAll when Accept All is clicked", () => {
    const onAcceptAll = vi.fn();
    renderModal({ onAcceptAll });
    fireEvent.click(screen.getByRole("button", { name: /accept all/i }));
    expect(onAcceptAll).toHaveBeenCalled();
  });

  it("calls onRejectNonEssential when Reject Non-Essential is clicked", () => {
    const onRejectNonEssential = vi.fn();
    renderModal({ onRejectNonEssential });
    fireEvent.click(
      screen.getByRole("button", { name: /reject non-essential/i }),
    );
    expect(onRejectNonEssential).toHaveBeenCalled();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("includes a link to the cookie policy", () => {
    renderModal();
    const links = screen.getAllByRole("link", { name: /cookie policy/i });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0]).toHaveAttribute("href", "/legal/cookies");
  });

  it("does not show analytics toggle when GA is not configured", () => {
    const originalEnv = process.env.NEXT_PUBLIC_GA_ID;
    delete process.env.NEXT_PUBLIC_GA_ID;
    renderModal();
    expect(
      screen.queryByRole("switch", { name: /analytics/i }),
    ).not.toBeInTheDocument();
    process.env.NEXT_PUBLIC_GA_ID = originalEnv;
  });
});
