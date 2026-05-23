import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addFrontendBreadcrumb,
  captureFrontendException,
  isFrontendMonitoringEnabled,
  resetFrontendBreadcrumbsForTesting,
} from "@/lib/observability";

describe("frontend observability", () => {
  const originalSentryDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  const originalSentryRate = process.env.NEXT_PUBLIC_SENTRY_ERROR_SAMPLE_RATE;
  const originalSentryEnvironment = process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT;
  const originalSentryRelease = process.env.NEXT_PUBLIC_SENTRY_RELEASE;

  beforeEach(() => {
    resetFrontendBreadcrumbsForTesting();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = originalSentryDsn;
    process.env.NEXT_PUBLIC_SENTRY_ERROR_SAMPLE_RATE = originalSentryRate;
    process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT = originalSentryEnvironment;
    process.env.NEXT_PUBLIC_SENTRY_RELEASE = originalSentryRelease;
    resetFrontendBreadcrumbsForTesting();
    vi.unstubAllGlobals();
  });

  it("disables monitoring safely when DSN is absent", async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = "";
    resetFrontendBreadcrumbsForTesting();

    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    expect(isFrontendMonitoringEnabled()).toBe(false);
    await captureFrontendException(new Error("test error"));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("captures sanitized payloads with request id when DSN is configured", async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = "https://public@sentry.example.com/42";
    process.env.NEXT_PUBLIC_SENTRY_ERROR_SAMPLE_RATE = "1";
    process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT = "test";
    process.env.NEXT_PUBLIC_SENTRY_RELEASE = "frontend-test";
    resetFrontendBreadcrumbsForTesting();

    addFrontendBreadcrumb({
      category: "chat.query",
      message: "Chat question submitted",
      data: {
        question: "sensitive question text",
      },
    });

    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    await captureFrontendException(new Error("failure"), {
      feature: "api.request",
      requestId: "req-123",
      extra: {
        question: "never send this",
        endpoint: "/api/v1/chat",
      },
    });

    expect(isFrontendMonitoringEnabled()).toBe(true);
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("https://sentry.example.com/api/42/store/");
    expect(url).toContain("sentry_key=public");

    const payload = JSON.parse(String(init.body)) as Record<string, unknown>;
    const tags = payload.tags as Record<string, unknown>;
    const extra = payload.extra as Record<string, unknown>;
    const context = extra.context as Record<string, unknown>;
    const breadcrumbs = payload.breadcrumbs as {
      values: Array<Record<string, unknown>>;
    };

    expect(tags.request_id).toBe("req-123");
    expect(context.question).toBe("[REDACTED]");
    expect(context.endpoint).toBe("/api/v1/chat");
    expect(breadcrumbs.values[0]?.data).toEqual({
      question: "[REDACTED]",
    });
  });
});
