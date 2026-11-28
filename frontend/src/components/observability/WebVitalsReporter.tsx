"use client";

import { useReportWebVitals } from "next/web-vitals";
import { useCallback, useEffect, useMemo } from "react";

import { useConsentContext } from "@/components/consent/ConsentProvider";
import { postWebVitals } from "@/lib/api/web-vitals";
import {
  createWebVitalsBatcher,
  toWebVitalSample,
  type ReportedWebVital,
} from "@/lib/observability/web-vitals";

/** First-party Web Vitals (R07-11): off unless the build flag is "true". */
export function isWebVitalsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_WEB_VITALS_ENABLED === "true";
}

function WebVitalsCollector() {
  const batcher = useMemo(
    () => createWebVitalsBatcher((samples) => void postWebVitals(samples)),
    [],
  );

  useReportWebVitals(
    useCallback(
      (metric: ReportedWebVital) => {
        const sample = toWebVitalSample(metric, window.location.pathname);
        if (sample) {
          batcher.add(sample);
        }
      },
      [batcher],
    ),
  );

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        batcher.flush();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      // Unmounting means consent was withdrawn: send nothing further.
      batcher.discard();
    };
  }, [batcher]);

  return null;
}

/**
 * Mounts the collector only when the build flag is on and the visitor granted
 * analytics consent. With either missing, no hook runs and nothing is sent.
 */
export function WebVitalsReporter() {
  const { isLoaded, decisions } = useConsentContext();

  if (!isWebVitalsEnabled() || !isLoaded || !decisions.analytics) {
    return null;
  }
  return <WebVitalsCollector />;
}
