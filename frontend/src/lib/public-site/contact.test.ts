import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import {
  ContactSubmissionError,
  resolveContactSubmissionConfig,
  submitContactForm,
} from "@/lib/public-site/contact";

const originalEnv = { ...process.env };

function baseFormValues() {
  return {
    fullName: "Alex Rivera",
    workEmail: "alex@example.com",
    company: "Rudix Labs",
    roleTitle: "Solutions Architect",
    useCase: "RAG pipeline optimization",
    teamSize: "51-250",
    message: "We need a demo focused on citation quality and governance.",
    consentAccepted: true,
    honeypot: "",
    captchaToken: "",
  };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  process.env = { ...originalEnv };
  delete process.env.NEXT_PUBLIC_CONTACT_SUBMIT_API_URL;
  delete process.env.NEXT_PUBLIC_CONTACT_SUBMIT_MAILTO;
  delete process.env.NEXT_PUBLIC_CONTACT_SUBMIT_EXTERNAL_URL;
  delete process.env.NEXT_PUBLIC_CONTACT_SCHEDULER_URL;
  delete process.env.NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER;
  delete process.env.NEXT_PUBLIC_CONTACT_CAPTCHA_SITE_KEY;
  delete process.env.NEXT_PUBLIC_SUPPORT_EMAIL;
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
});

afterEach(() => {
  vi.unstubAllGlobals();
  process.env = { ...originalEnv };
});

describe("resolveContactSubmissionConfig", () => {
  it("defaults to unavailable when no submission mode is configured", () => {
    const config = resolveContactSubmissionConfig(resolvePublicSiteLinks());

    expect(config.mode).toBe("unavailable");
    expect(config.apiEndpoint).toBeNull();
    expect(config.mailtoAddress).toBeNull();
    expect(config.externalSubmitUrl).toBeNull();
  });

  it("prefers api mode when endpoint is configured", () => {
    process.env.NEXT_PUBLIC_CONTACT_SUBMIT_API_URL =
      "https://api.example.com/contact";

    const config = resolveContactSubmissionConfig(resolvePublicSiteLinks());

    expect(config.mode).toBe("api");
    expect(config.apiEndpoint).toBe("https://api.example.com/contact");
  });

  it("uses mailto mode when support email is configured", () => {
    process.env.NEXT_PUBLIC_SUPPORT_EMAIL = "support@example.com";

    const config = resolveContactSubmissionConfig(resolvePublicSiteLinks());

    expect(config.mode).toBe("mailto");
    expect(config.mailtoAddress).toBe("mailto:support@example.com");
  });

  it("uses external mode when a demo url is external", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://cal.example.com/rudix";

    const config = resolveContactSubmissionConfig(resolvePublicSiteLinks());

    expect(config.mode).toBe("external");
    expect(config.externalSubmitUrl).toBe("https://cal.example.com/rudix");
  });
});

describe("submitContactForm", () => {
  it("submits via api mode and returns success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitContactForm(baseFormValues(), {
      mode: "api",
      apiEndpoint: "https://api.example.com/contact",
      mailtoAddress: null,
      externalSubmitUrl: null,
      schedulerUrl: null,
      captchaProvider: null,
      captchaSiteKey: null,
    });

    expect(result.channel).toBe("api");
    expect(result.redirectTo).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("maps api validation response to safe error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "bad request" }), {
          status: 422,
        }),
      ),
    );

    await expect(
      submitContactForm(baseFormValues(), {
        mode: "api",
        apiEndpoint: "https://api.example.com/contact",
        mailtoAddress: null,
        externalSubmitUrl: null,
        schedulerUrl: null,
        captchaProvider: null,
        captchaSiteKey: null,
      }),
    ).rejects.toMatchObject({
      kind: "validation_failure",
      safeMessage: "Some fields need attention. Review the form and try again.",
    } satisfies Partial<ContactSubmissionError>);
  });

  it("returns a prefilled mailto redirect for mailto mode", async () => {
    const result = await submitContactForm(baseFormValues(), {
      mode: "mailto",
      apiEndpoint: null,
      mailtoAddress: "mailto:sales@example.com",
      externalSubmitUrl: null,
      schedulerUrl: null,
      captchaProvider: null,
      captchaSiteKey: null,
    });

    expect(result.channel).toBe("mailto");
    expect(result.redirectTo).toContain("mailto:sales@example.com");
    expect(result.redirectTo).toContain("subject=");
  });

  it("returns external redirect for external mode", async () => {
    const result = await submitContactForm(baseFormValues(), {
      mode: "external",
      apiEndpoint: null,
      mailtoAddress: null,
      externalSubmitUrl: "https://cal.example.com/rudix",
      schedulerUrl: "https://cal.example.com/rudix",
      captchaProvider: null,
      captchaSiteKey: null,
    });

    expect(result.channel).toBe("external");
    expect(result.redirectTo).toBe("https://cal.example.com/rudix");
  });

  it("silently succeeds when honeypot is filled", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitContactForm(
      {
        ...baseFormValues(),
        honeypot: "bot-text",
      },
      {
        mode: "api",
        apiEndpoint: "https://api.example.com/contact",
        mailtoAddress: null,
        externalSubmitUrl: null,
        schedulerUrl: null,
        captchaProvider: null,
        captchaSiteKey: null,
      },
    );

    expect(result.channel).toBe("api");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
