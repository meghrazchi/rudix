import type { components } from "@/lib/api/generated/schema";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

export type WebVitalsBatchRequest =
  components["schemas"]["WebVitalsBatchRequest"];

/**
 * Sends Web Vitals samples to the first-party ingest endpoint (R07-11).
 * A plain `fetch`: no Authorization header, no cookies, never throws, and
 * `keepalive` so a batch flushed while the page is hiding still goes out.
 */
export async function postWebVitals(
  samples: WebVitalsBatchRequest["samples"],
): Promise<void> {
  if (samples.length === 0) {
    return;
  }
  const apiBase = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
  const body: WebVitalsBatchRequest = { samples };
  try {
    await fetch(`${apiBase}/telemetry/web-vitals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
      credentials: "omit",
    });
  } catch {
    // Telemetry must never affect the page.
  }
}
