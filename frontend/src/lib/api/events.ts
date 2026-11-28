/**
 * Open authenticated Server-Sent Event streams with `fetch` (R07-07).
 *
 * Used by the per-user realtime stream (`GET /events/stream`) and the agent run stream
 * (`GET /agent/runs/{run_id}/stream`). The bearer token comes from
 * `getSessionRequestContext()` and is sent in the `Authorization` header, never in the
 * URL. The organisation header follows the rule of `request.ts`.
 */

import { getSessionRequestContext } from "@/lib/api/request";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const REALTIME_STREAM_PATH = "/events/stream";

export function agentRunStreamPath(runId: string): string {
  return `/agent/runs/${encodeURIComponent(runId)}/stream`;
}

function shouldAttachOrganizationHeader(organizationId: string): boolean {
  if (getFrontendRuntimeConfig().authProvider !== "app") {
    return true;
  }
  return UUID_PATTERN.test(organizationId);
}

export type OpenEventStreamOptions = {
  lastEventId?: string | null;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
};

/** `fetch` the stream; the caller checks `response.status` and reads the body. */
export async function openEventStream(
  path: string,
  options: OpenEventStreamOptions = {},
): Promise<Response> {
  const context = getSessionRequestContext();
  const headers = new Headers({
    Accept: "text/event-stream",
    "Cache-Control": "no-store",
  });
  if (context.token) {
    headers.set("Authorization", `Bearer ${context.token}`);
  }
  if (
    context.organizationId &&
    shouldAttachOrganizationHeader(context.organizationId)
  ) {
    headers.set("X-Organization-ID", context.organizationId);
  }
  if (options.lastEventId) {
    headers.set("Last-Event-ID", options.lastEventId);
  }
  const base = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
  const doFetch = options.fetchImpl ?? fetch;
  return doFetch(`${base}${path}`, {
    method: "GET",
    headers,
    cache: "no-store",
    signal: options.signal,
  });
}
