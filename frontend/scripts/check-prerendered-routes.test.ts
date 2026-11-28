// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import staticPublicRoutes from "../config/static-public-routes.json";
import { SUPPORTED_LOCALES } from "../src/i18n/routing";

const SCRIPT = path.join(__dirname, "check-prerendered-routes.mjs");
const tempDirs: string[] = [];

function allRoutes(): string[] {
  return SUPPORTED_LOCALES.flatMap((locale) =>
    staticPublicRoutes.map(
      (routePath) => `/${locale}${routePath === "/" ? "" : routePath}`,
    ),
  );
}

function runWithManifest(
  routes: string[] | null,
  options: { viaArgument?: boolean } = {},
) {
  const distDir = mkdtempSync(path.join(tmpdir(), "prerender-check-"));
  tempDirs.push(distDir);
  if (routes) {
    writeFileSync(
      path.join(distDir, "prerender-manifest.json"),
      JSON.stringify({
        routes: Object.fromEntries(routes.map((route) => [route, {}])),
      }),
    );
  }
  if (options.viaArgument) {
    return spawnSync(process.execPath, [SCRIPT, "--dist-dir", distDir], {
      encoding: "utf8",
      env: { ...process.env, NEXT_DIST_DIR: "/nonexistent-dist-dir" },
    });
  }
  return spawnSync(process.execPath, [SCRIPT], {
    encoding: "utf8",
    env: { ...process.env, NEXT_DIST_DIR: distDir },
  });
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("scripts/check-prerendered-routes.mjs", () => {
  it("passes when every public path is prerendered for every locale", () => {
    const result = runWithManifest([...allRoutes(), "/robots.txt"]);
    expect(result.status).toBe(0);
    expect(result.stdout).toContain(
      `All ${allRoutes().length} static public routes`,
    );
  });

  it("lists the missing routes and exits 1", () => {
    const routes = allRoutes().filter(
      (route) => route !== "/fa/pricing" && route !== "/de",
    );
    const result = runWithManifest(routes);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("2 of");
    expect(result.stderr).toContain("/fa/pricing");
    expect(result.stderr).toContain("  /de\n");
  });

  it("reads the build dir from --dist-dir before NEXT_DIST_DIR", () => {
    const result = runWithManifest(allRoutes(), { viaArgument: true });
    expect(result.status).toBe(0);
    const missing = runWithManifest(null, { viaArgument: true });
    expect(missing.status).toBe(1);
    expect(missing.stderr).toContain("prerender-check-");
  });

  it("exits 1 when the manifest is missing", () => {
    const result = runWithManifest(null);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("run next build first");
  });
});
