#!/usr/bin/env node
// Fails when a static public page is not prerendered for every locale (R07-01).
// Run after `next build`: reads .next/prerender-manifest.json and expects
// `/${locale}${path}` for every path in config/static-public-routes.json and
// every locale in SUPPORTED_LOCALES (src/i18n/routing.ts).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const distDir = process.env.NEXT_DIST_DIR || ".next";

function readJson(relativePath) {
  // path.resolve keeps an absolute NEXT_DIST_DIR as is.
  return JSON.parse(
    readFileSync(path.resolve(frontendRoot, relativePath), "utf8"),
  );
}

function readSupportedLocales() {
  const source = readFileSync(
    path.join(frontendRoot, "src/i18n/routing.ts"),
    "utf8",
  );
  const match = source.match(/SUPPORTED_LOCALES\s*=\s*\[([^\]]*)\]/);
  if (!match) {
    throw new Error("SUPPORTED_LOCALES not found in src/i18n/routing.ts");
  }
  return [...match[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1]);
}

let manifest;
try {
  manifest = readJson(path.join(distDir, "prerender-manifest.json"));
} catch (error) {
  console.error(
    `Cannot read ${distDir}/prerender-manifest.json (run next build first): ${error.message}`,
  );
  process.exit(1);
}

const routes = new Set(Object.keys(manifest.routes ?? {}));
const paths = readJson("config/static-public-routes.json");
const locales = readSupportedLocales();
const expected = locales.flatMap((locale) =>
  paths.map((routePath) => `/${locale}${routePath === "/" ? "" : routePath}`),
);
const missing = expected.filter((route) => !routes.has(route));

if (missing.length > 0) {
  console.error(
    `${missing.length} of ${expected.length} static public routes are not prerendered:`,
  );
  for (const route of missing) {
    console.error(`  ${route}`);
  }
  process.exit(1);
}

console.log(
  `All ${expected.length} static public routes (${paths.length} paths x ${locales.length} locales) are prerendered.`,
);
