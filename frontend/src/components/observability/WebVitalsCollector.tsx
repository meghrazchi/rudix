"use client";

import { useReportWebVitals } from "next/web-vitals";
import { useCallback, useEffect, useMemo } from "react";

import { postWebVitals } from "@/lib/api/web-vitals";
import {
  createWebVitalsBatcher,
  toWebVitalSample,
  type ReportedWebVital,
} from "@/lib/observability/web-vitals";

export function WebVitalsCollector() {
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
