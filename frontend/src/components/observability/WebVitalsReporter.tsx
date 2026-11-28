"use client";

import { lazy, Suspense } from "react";

import { useConsentContext } from "@/components/consent/ConsentProvider";

// Loaded on demand: with the flag off or no consent, the web-vitals code never
// reaches the browser (keeps every route inside its bundle budget). React.lazy
// rather than next/dynamic so the root layout does not ship the next/dynamic
// loader to every route.
const WebVitalsCollector = lazy(() =>
  import("@/components/observability/WebVitalsCollector").then((module) => ({
    default: module.WebVitalsCollector,
  })),
);

/** First-party Web Vitals (R07-11): off unless the build flag is "true". */
export function isWebVitalsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_WEB_VITALS_ENABLED === "true";
}

/**
 * Mounts the collector only when the build flag is on and the visitor granted
 * analytics consent. With either missing, no hook runs and nothing is sent.
 * Consent loads on the client only, so the collector never renders on the server.
 */
export function WebVitalsReporter() {
  const { isLoaded, decisions } = useConsentContext();

  if (!isWebVitalsEnabled() || !isLoaded || !decisions.analytics) {
    return null;
  }
  return (
    <Suspense fallback={null}>
      <WebVitalsCollector />
    </Suspense>
  );
}
