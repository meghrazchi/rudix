import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";

import { CookieConsentBanner } from "@/components/consent/CookieConsentBanner";
import { ConsentProvider } from "@/components/consent/ConsentProvider";
import { CONSENT_POLICY_VERSION, writeConsentRecord } from "@/lib/consent";
import { renderWithProviders } from "@/test/render";

function renderBanner() {
  return renderWithProviders(
    <ConsentProvider>
      <CookieConsentBanner />
    </ConsentProvider>,
  );
}

describe("CookieConsentBanner", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the banner when no consent record exists", async () => {
    renderBanner();
    expect(
      await screen.findByRole("dialog", { name: /cookie consent/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /accept all/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /reject non-essential/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /customize/i }),
    ).toBeInTheDocument();
  });

  it("does not render when a valid consent record already exists", () => {
    writeConsentRecord({
      policyVersion: CONSENT_POLICY_VERSION,
      timestamp: Date.now(),
      decisions: { functional: true, analytics: false },
    });
    renderBanner();
    expect(
      screen.queryByRole("dialog", { name: /cookie consent/i }),
    ).not.toBeInTheDocument();
  });

  it("shows banner when consent record has an old policy version", async () => {
    writeConsentRecord({
      policyVersion: "0.1",
      timestamp: Date.now(),
      decisions: { functional: true, analytics: false },
    });
    renderBanner();
    expect(
      await screen.findByRole("dialog", { name: /cookie consent/i }),
    ).toBeInTheDocument();
  });

  it("accepts all and hides the banner", async () => {
    renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: /accept all/i }));
    expect(
      screen.queryByRole("dialog", { name: /cookie consent/i }),
    ).not.toBeInTheDocument();

    const raw = window.localStorage.getItem("rudix.consent.v1");
    expect(raw).not.toBeNull();
    const record = JSON.parse(raw!);
    expect(record.decisions.analytics).toBe(true);
    expect(record.decisions.functional).toBe(true);
  });

  it("rejects non-essential and hides the banner", async () => {
    renderBanner();
    fireEvent.click(
      await screen.findByRole("button", { name: /reject non-essential/i }),
    );
    expect(
      screen.queryByRole("dialog", { name: /cookie consent/i }),
    ).not.toBeInTheDocument();

    const raw = window.localStorage.getItem("rudix.consent.v1");
    expect(raw).not.toBeNull();
    const record = JSON.parse(raw!);
    expect(record.decisions.analytics).toBe(false);
    expect(record.decisions.functional).toBe(false);
  });

  it("opens the preferences modal when customize is clicked", async () => {
    renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: /customize/i }));
    expect(
      await screen.findByRole("dialog", { name: /cookie preferences/i }),
    ).toBeInTheDocument();
  });

  it("includes a link to the cookie policy", async () => {
    renderBanner();
    const link = await screen.findByRole("link", { name: /cookie policy/i });
    expect(link).toHaveAttribute("href", "/legal/cookies");
  });
});
