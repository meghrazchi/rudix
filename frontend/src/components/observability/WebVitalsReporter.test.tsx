import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { consent, reportHook, postWebVitals } = vi.hoisted(() => ({
  consent: {
    current: {
      isLoaded: true,
      decisions: { functional: true, analytics: true },
    },
  },
  reportHook: vi.fn(),
  postWebVitals: vi.fn((samples: Array<{ name: string }>) => {
    void samples;
    return Promise.resolve();
  }),
}));

vi.mock("@/components/consent/ConsentProvider", () => ({
  useConsentContext: () => consent.current,
}));
vi.mock("next/web-vitals", () => ({ useReportWebVitals: reportHook }));
vi.mock("@/lib/api/web-vitals", () => ({ postWebVitals }));

import { WebVitalsReporter } from "@/components/observability/WebVitalsReporter";

type Callback = (metric: {
  name: string;
  value: number;
  rating?: string;
  navigationType?: string;
}) => void;

function lastCallback(): Callback {
  const calls = reportHook.mock.calls;
  return calls[calls.length - 1][0] as Callback;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  consent.current = {
    isLoaded: true,
    decisions: { functional: true, analytics: true },
  };
  reportHook.mockClear();
  postWebVitals.mockClear();
  vi.stubEnv("NEXT_PUBLIC_WEB_VITALS_ENABLED", "true");
});

afterEach(() => {
  vi.unstubAllEnvs();
  setVisibility("visible");
});

describe("WebVitalsReporter", () => {
  it("does nothing when the build flag is off", () => {
    vi.stubEnv("NEXT_PUBLIC_WEB_VITALS_ENABLED", "false");
    render(<WebVitalsReporter />);
    expect(reportHook).not.toHaveBeenCalled();
    setVisibility("hidden");
    expect(postWebVitals).not.toHaveBeenCalled();
  });

  it("does nothing by default", () => {
    vi.stubEnv("NEXT_PUBLIC_WEB_VITALS_ENABLED", "");
    render(<WebVitalsReporter />);
    expect(reportHook).not.toHaveBeenCalled();
  });

  it("does nothing without analytics consent", () => {
    consent.current = {
      isLoaded: true,
      decisions: { functional: true, analytics: false },
    };
    render(<WebVitalsReporter />);
    expect(reportHook).not.toHaveBeenCalled();
    expect(postWebVitals).not.toHaveBeenCalled();
  });

  it("does nothing before the consent state has loaded", () => {
    consent.current = {
      isLoaded: false,
      decisions: { functional: true, analytics: true },
    };
    render(<WebVitalsReporter />);
    expect(reportHook).not.toHaveBeenCalled();
  });

  it("batches samples and flushes when the page becomes hidden", () => {
    render(<WebVitalsReporter />);
    const report = lastCallback();

    act(() => {
      report({ name: "LCP", value: 1200, rating: "good" });
      report({ name: "CLS", value: 0.02, rating: "good" });
      report({ name: "FID", value: 5 });
    });
    expect(postWebVitals).not.toHaveBeenCalled();

    act(() => setVisibility("hidden"));
    expect(postWebVitals).toHaveBeenCalledTimes(1);
    const sent = postWebVitals.mock.calls[0][0];
    expect(sent.map((s) => s.name)).toEqual(["LCP", "CLS"]);
  });

  it("sends a full batch of 10 immediately", () => {
    render(<WebVitalsReporter />);
    const report = lastCallback();
    act(() => {
      for (let i = 0; i < 10; i += 1) {
        report({ name: "INP", value: i, rating: "good" });
      }
    });
    expect(postWebVitals).toHaveBeenCalledTimes(1);
    expect(postWebVitals.mock.calls[0][0]).toHaveLength(10);
  });

  it("drops pending samples when consent is withdrawn", () => {
    const { rerender } = render(<WebVitalsReporter />);
    const report = lastCallback();
    act(() => report({ name: "LCP", value: 10, rating: "good" }));

    consent.current = {
      isLoaded: true,
      decisions: { functional: true, analytics: false },
    };
    rerender(<WebVitalsReporter />);
    act(() => setVisibility("hidden"));

    expect(postWebVitals).not.toHaveBeenCalled();
  });
});
