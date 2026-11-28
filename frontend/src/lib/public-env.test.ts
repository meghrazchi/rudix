import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEV_ONLY_FLAGS,
  DEV_ONLY_SECRETS,
} from "../../config/build-env-validation.mjs";
import {
  BUILD_ONLY_PUBLIC_KEYS,
  PUBLIC_RUNTIME_KEYS,
  isPublicRuntimeKey,
  resolveRuntimeConfigSource,
} from "../../config/public-runtime-keys.mjs";
import { publicEnv, publicEnvSource, runtimeConfigSource } from "./public-env";
import { getFrontendRuntimeConfig } from "./runtime-config";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

function setServed(values: Record<string, string> | undefined): void {
  if (values === undefined) {
    delete window.__RUDIX_RUNTIME_CONFIG__;
  } else {
    window.__RUDIX_RUNTIME_CONFIG__ = Object.freeze({ ...values });
  }
}

afterEach(() => {
  vi.unstubAllEnvs();
  setServed(undefined);
});

describe("runtimeConfigSource", () => {
  it.each([
    [undefined, "build"],
    ["", "build"],
    ["build", "build"],
    ["bogus", "build"],
    ["request", "request"],
    [" Request ", "request"],
  ])("maps %s to %s", (value, expected) => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", value);
    expect(runtimeConfigSource()).toBe(expected);
    expect(resolveRuntimeConfigSource(value)).toBe(expected);
  });
});

describe("publicEnv in build mode (default)", () => {
  it("returns the build value and ignores served values", () => {
    setServed({ NEXT_PUBLIC_GA_ID: "G-SERVED" });
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-BUILD");
    expect(publicEnv("NEXT_PUBLIC_GA_ID", undefined)).toBeUndefined();
  });

  it("parses process.env itself in runtime-config", () => {
    setServed({ NEXT_PUBLIC_API_URL: "https://served.example.com/api/v1" });
    expect(publicEnvSource()).toBe(process.env);
  });
});

describe("publicEnv in request mode (browser)", () => {
  it("prefers the served value, including an empty string", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    setServed({ NEXT_PUBLIC_GA_ID: "G-SERVED", NEXT_PUBLIC_SUPPORT_URL: "" });
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-SERVED");
    expect(publicEnv("NEXT_PUBLIC_SUPPORT_URL", "/build")).toBe("");
  });

  it("falls back to the build value when not served", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-BUILD");
    setServed({});
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-BUILD");
  });

  it("feeds served values to runtime-config", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://build.example.com/api/v1");
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://app.example.com");
    expect(getFrontendRuntimeConfig().apiUrl).toBe(
      "https://build.example.com/api/v1",
    );
    setServed({ NEXT_PUBLIC_API_URL: "https://served.example.com/api/v1/" });
    expect(getFrontendRuntimeConfig().apiUrl).toBe(
      "https://served.example.com/api/v1",
    );
    expect(publicEnvSource().NEXT_PUBLIC_APP_URL).toBe(
      "https://app.example.com",
    );
  });
});

describe("public runtime key lists", () => {
  it("has no duplicates and only NEXT_PUBLIC_ names", () => {
    expect(new Set(PUBLIC_RUNTIME_KEYS).size).toBe(PUBLIC_RUNTIME_KEYS.length);
    for (const name of [
      ...PUBLIC_RUNTIME_KEYS,
      ...Object.keys(BUILD_ONLY_PUBLIC_KEYS),
    ]) {
      expect(name).toMatch(/^NEXT_PUBLIC_[A-Z0-9_]+$/);
    }
  });

  it("never allowlists a development-only flag or secret", () => {
    for (const name of [...DEV_ONLY_FLAGS, ...DEV_ONLY_SECRETS]) {
      expect(isPublicRuntimeKey(name)).toBe(false);
      expect(BUILD_ONLY_PUBLIC_KEYS[name]).toBeTruthy();
    }
  });

  it("keeps the allowlist and the build-only list disjoint", () => {
    const overlap = Object.keys(BUILD_ONLY_PUBLIC_KEYS).filter((name) =>
      isPublicRuntimeKey(name),
    );
    expect(overlap).toEqual([]);
    for (const reason of Object.values(BUILD_ONLY_PUBLIC_KEYS)) {
      expect(reason.length).toBeGreaterThan(10);
    }
  });

  it("keeps the PublicRuntimeKey type equal to the allowlist", () => {
    const declaration = fs.readFileSync(
      path.join(frontendRoot, "config/public-runtime-keys.d.mts"),
      "utf8",
    );
    const union = declaration.match(/PublicRuntimeKey =([^;]*);/)?.[1] ?? "";
    const typed = [...union.matchAll(/"([A-Z0-9_]+)"/g)].map((m) => m[1]);
    expect([...typed].sort()).toEqual([...PUBLIC_RUNTIME_KEYS].sort());
  });
});

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "test" && entry.name !== "__tests__") {
        files.push(...collectSourceFiles(full));
      }
    } else if (
      /\.(ts|tsx)$/.test(entry.name) &&
      !/\.(test|spec)\.(ts|tsx)$/.test(entry.name) &&
      !entry.name.endsWith(".d.ts")
    ) {
      files.push(full);
    }
  }
  return files;
}

describe("NEXT_PUBLIC_* names read in src/", () => {
  const files = collectSourceFiles(path.join(frontendRoot, "src"));

  it("are all allowlisted or build-only with a reason", () => {
    const unknown: string[] = [];
    for (const file of files) {
      const source = fs.readFileSync(file, "utf8");
      for (const match of source.matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g)) {
        const name = match[0];
        if (!isPublicRuntimeKey(name) && !BUILD_ONLY_PUBLIC_KEYS[name]) {
          unknown.push(`${path.relative(frontendRoot, file)}:${name}`);
        }
      }
    }
    expect(unknown).toEqual([]);
  });

  it("read allowlisted names through publicEnv()", () => {
    const direct: string[] = [];
    const literal = /process\.env\.(NEXT_PUBLIC_[A-Z0-9_]+)/g;
    for (const file of files) {
      const source = fs.readFileSync(file, "utf8");
      // The build value passed to publicEnv is the one allowed literal read.
      const withoutWrapped = source.replace(
        /publicEnv\(\s*"(NEXT_PUBLIC_[A-Z0-9_]+)",\s*process\.env\.\1,?\s*\)/g,
        "",
      );
      for (const match of withoutWrapped.matchAll(literal)) {
        if (isPublicRuntimeKey(match[1])) {
          direct.push(`${path.relative(frontendRoot, file)}:${match[1]}`);
        }
      }
    }
    expect(direct).toEqual([]);
  });

  it("passes the matching literal read to publicEnv()", () => {
    const mismatched: string[] = [];
    const call =
      /publicEnv\(\s*"(NEXT_PUBLIC_[A-Z0-9_]+)",\s*process\.env\.(NEXT_PUBLIC_[A-Z0-9_]+)/g;
    for (const file of files) {
      const source = fs.readFileSync(file, "utf8");
      for (const match of source.matchAll(call)) {
        if (match[1] !== match[2]) {
          mismatched.push(`${path.relative(frontendRoot, file)}:${match[1]}`);
        }
      }
    }
    expect(mismatched).toEqual([]);
  });
});
