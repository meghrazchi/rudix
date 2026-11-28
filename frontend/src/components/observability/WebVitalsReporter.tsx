"use client";

import dynamic from "next/dynamic";

import { useConsentContext } from "@/components/consent/ConsentProvider";

// Loaded on demand: with the flag off or no consent, the web-vitals code never
// reaches the browser (keeps every route inside its bundle budget).
const WebVitalsCollector = dynamic(
  () =>
    import("@/components/observability/WebVitalsCollector").then(
      (module) => module.WebVitalsCollector,
    ),
  { ssr: false },
);

/** First-party Web Vitals (R07-11): off unless the build flag is "true". */
export function isWebVitalsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_WEB_VITALS_ENABLED === "true";
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
