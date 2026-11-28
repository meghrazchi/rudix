// Public configuration accessor (R08-11).
//
// publicEnv(name, buildValue) returns the value of an allowlisted
// NEXT_PUBLIC_* name. Callers pass the literal read as the build value:
//
//   publicEnv("NEXT_PUBLIC_GA_ID", process.env.NEXT_PUBLIC_GA_ID)
//
// because Next inlines only literal process.env reads of NEXT_PUBLIC_ names. A
// literal at each call site keeps every bundle as small as before; one shared
// map of all names would ship to every route and break the marketing budget.
//
// - Build mode (NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE unset or "build", the
//   default): the build value, exactly as the direct read it replaces.
// - Request mode: in the browser, the value served by /runtime-config.js
//   (window.__RUDIX_RUNTIME_CONFIG__) when present; on the server, the runtime
//   environment when set; otherwise the build value.
//
// The allowlist is config/public-runtime-keys.mjs; public-env.test.ts keeps
// the PublicRuntimeKey type equal to it and scans src/ for names outside it.

import type { PublicRuntimeKey } from "../../config/public-runtime-keys.mjs";

export type { PublicRuntimeKey };

declare global {
  interface Window {
    __RUDIX_RUNTIME_CONFIG__?: Readonly<Record<string, string>>;
  }
}

// Same rule as resolveRuntimeConfigSource in config/public-runtime-keys.mjs,
// which is not imported here: it would ship both name lists to the browser.
export function runtimeConfigSource(): "build" | "request" {
  const value = process.env.NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE ?? "";
  return value.trim().toLowerCase() === "request" ? "request" : "build";
}

function servedConfig(): Readonly<Record<string, string>> | undefined {
  return typeof window === "undefined"
    ? undefined
    : window.__RUDIX_RUNTIME_CONFIG__;
}

export function publicEnv(
  name: PublicRuntimeKey,
  buildValue: string | undefined,
): string | undefined {
  if (runtimeConfigSource() !== "request") {
    return buildValue;
  }
  if (typeof window !== "undefined") {
    const served = servedConfig();
    return served && Object.hasOwn(served, name) ? served[name] : buildValue;
  }
  // Server side: a dynamic read is not inlined, so it sees the runtime env.
  return process.env[name] ?? buildValue;
}

/**
 * The environment object runtime-config.ts parses. Build mode: process.env,
 * unchanged. Request mode in the browser: process.env with the served
 * request-time values on top (the server reads its runtime env directly).
 */
export function publicEnvSource(): NodeJS.ProcessEnv {
  const served = runtimeConfigSource() === "request" ? servedConfig() : null;
  return served ? { ...process.env, ...served } : process.env;
}
