import type { Request } from "@playwright/test";

/**
 * CORS headers for mocked API responses, mirroring the backend's
 * CORSMiddleware (explicit origin + `allow_credentials=True`).
 *
 * Browsers reject a wildcard `Access-Control-Allow-Origin: *` for requests
 * sent with `credentials: "include"` (sign-in, refresh, logout), so mocks
 * must echo the request origin and allow credentials, as the real API does.
 */
export function mockCorsHeaders(request: Request): Record<string, string> {
  const headers = request.headers();
  const origin = headers["origin"];
  const requestedHeaders = headers["access-control-request-headers"];

  return {
    "access-control-allow-origin": origin ?? "*",
    ...(origin
      ? { "access-control-allow-credentials": "true", vary: "Origin" }
      : {}),
    "access-control-allow-headers": requestedHeaders ?? "*",
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "access-control-expose-headers": "X-Request-ID",
  };
}
