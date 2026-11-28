import { act, render, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

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

async function reportFunction(): Promise<Callback> {
  await waitFor(() => expect(reportHook).toHaveBeenCalled());
  return lastCallback();
}

// The collector is a lazy module: render inside an async act so the import
// resolves and its effects (the visibility listener) commit before asserting.
async function renderReporter(): Promise<ReturnType<typeof render>> {
  let result: ReturnType<typeof render> | undefined;
  await act(async () => {
    result = render(<WebVitalsReporter />);
  });
  return result as ReturnType<typeof render>;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeAll(async () => {
  // Warm the on-demand collector module so the lazy import resolves promptly.
  await import("@/components/observability/WebVitalsCollector");
});

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
  it("does nothing when the build flag is off", async () => {
    vi.stubEnv("NEXT_PUBLIC_WEB_VITALS_ENABLED", "false");
    await renderReporter();
    expect(reportHook).not.toHaveBeenCalled();
    setVisibility("hidden");
    expect(postWebVitals).not.toHaveBeenCalled();
  });

  it("does nothing by default", async () => {
    vi.stubEnv("NEXT_PUBLIC_WEB_VITALS_ENABLED", "");
    await renderReporter();
    expect(reportHook).not.toHaveBeenCalled();
  });

  it("does nothing without analytics consent", async () => {
    consent.current = {
      isLoaded: true,
      decisions: { functional: true, analytics: false },
    };
    await renderReporter();
    expect(reportHook).not.toHaveBeenCalled();
    expect(postWebVitals).not.toHaveBeenCalled();
  });

  it("does nothing before the consent state has loaded", async () => {
    consent.current = {
      isLoaded: false,
      decisions: { functional: true, analytics: true },
    };
    await renderReporter();
    expect(reportHook).not.toHaveBeenCalled();
  });

  it("batches samples and flushes when the page becomes hidden", async () => {
    await renderReporter();
    const report = await reportFunction();

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

  it("sends a full batch of 10 immediately", async () => {
    await renderReporter();
    const report = await reportFunction();
    act(() => {
      for (let i = 0; i < 10; i += 1) {
        report({ name: "INP", value: i, rating: "good" });
      }
    });
    expect(postWebVitals).toHaveBeenCalledTimes(1);
    expect(postWebVitals.mock.calls[0][0]).toHaveLength(10);
  });

  it("drops pending samples when consent is withdrawn", async () => {
    const { rerender } = await renderReporter();
    const report = await reportFunction();
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
