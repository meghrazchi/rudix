// Body of /runtime-config.js (R08-11): the allowlisted NEXT_PUBLIC_* values of
// the server's runtime environment, frozen on window before the app runs.

import { pickPublicRuntimeValues } from "../../config/public-runtime-keys.mjs";

const SCRIPT_UNSAFE_CHARACTERS: Record<string, string> = {
  "<": "\\u003c",
  ">": "\\u003e",
  "&": "\\u0026",
  "\u2028": "\\u2028",
  "\u2029": "\\u2029",
};

/** JSON that cannot close a script element or break a JS string literal. */
export function toScriptSafeJson(value: unknown): string {
  return JSON.stringify(value).replace(
    /[<>&\u2028\u2029]/g,
    (character) => SCRIPT_UNSAFE_CHARACTERS[character] ?? character,
  );
}

export function buildRuntimeConfigScript(
  env: Record<string, string | undefined>,
): string {
  const values = pickPublicRuntimeValues(env);
  return `window.__RUDIX_RUNTIME_CONFIG__=Object.freeze(${toScriptSafeJson(values)});\n`;
}

export const RUNTIME_CONFIG_PATH = "/runtime-config.js";

const COMMON_HEADERS = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};

/**
 * The /runtime-config.js response, served by the proxy (src/proxy.ts) rather
 * than an app route: a route segment is listed in the prerendered RSC payload
 * and would change every page in build mode. Build mode answers 404.
 */
export function runtimeConfigResponse(
  source: "build" | "request",
  env: Record<string, string | undefined>,
): Response {
  if (source !== "request") {
    return new Response("Not Found", {
      status: 404,
      headers: {
        ...COMMON_HEADERS,
        "Content-Type": "text/plain; charset=utf-8",
      },
    });
  }
  return new Response(buildRuntimeConfigScript(env), {
    status: 200,
    headers: {
      ...COMMON_HEADERS,
      "Content-Type": "application/javascript; charset=utf-8",
    },
  });
}
