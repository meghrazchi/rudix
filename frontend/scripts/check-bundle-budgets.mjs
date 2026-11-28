#!/usr/bin/env node
// Fails when a route's first-load JS exceeds its budget (R07-03).
// Run after `next build`: reads <distDir>/diagnostics/route-bundle-stats.json
// and config/bundle-budgets.json, prints route/raw/gzip/budget, writes
// <distDir>/bundle-report.json. A missing stats file is an error so a Next.js
// upgrade cannot switch the gate off silently.
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { computeRouteSizes, evaluateBudgets } from "./bundle-budgets-lib.mjs";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const distDir = process.env.NEXT_DIST_DIR || ".next";
const budgetsPath =
  process.env.BUNDLE_BUDGETS_FILE ||
  path.join(frontendRoot, "config/bundle-budgets.json");

function fail(message) {
  console.error(message);
  process.exit(1);
}

let stats;
const statsPath = path.resolve(
  frontendRoot,
  distDir,
  "diagnostics/route-bundle-stats.json",
);
try {
  stats = JSON.parse(readFileSync(statsPath, "utf8"));
} catch (error) {
  fail(
    `Cannot read ${statsPath} (run next build first; if a Next.js upgrade stopped writing it, update this gate): ${error.message}`,
  );
}

let budgets;
try {
  budgets = JSON.parse(readFileSync(budgetsPath, "utf8"));
} catch (error) {
  fail(`Cannot read ${budgetsPath}: ${error.message}`);
}

let sizes;
try {
  // Chunk paths in the stats are relative to the frontend root.
  sizes = computeRouteSizes(stats, (chunkPath) =>
    readFileSync(path.resolve(frontendRoot, chunkPath)),
  );
} catch (error) {
  fail(`Cannot measure route bundles: ${error.message}`);
}

const { rows, violations, unmatched } = evaluateBudgets(sizes, budgets);
const kb = (bytes) => (bytes / 1000).toFixed(1).padStart(8);
console.log(
  `${"route".padEnd(46)} ${"raw KB".padStart(8)} ${"gzip KB".padStart(8)} ${"budget KB".padStart(9)}  group`,
);
for (const row of [...rows].sort((a, b) => b.gzipBytes - a.gzipBytes)) {
  const flag = violations.includes(row) ? "  OVER" : "";
  console.log(
    `${row.route.padEnd(46)} ${kb(row.rawBytes)} ${kb(row.gzipBytes)} ${String(row.budgetKb).padStart(9)}  ${row.budgetName}${flag}`,
  );
}

writeFileSync(
  path.resolve(frontendRoot, distDir, "bundle-report.json"),
  JSON.stringify(
    {
      compression: budgets.compression,
      routes: rows.map((row) => ({
        route: row.route,
        rawBytes: row.rawBytes,
        gzipBytes: row.gzipBytes,
        budgetKb: row.budgetKb,
        budget: row.budgetName,
      })),
      unmatched,
    },
    null,
    2,
  ),
);

if (unmatched.length > 0) {
  console.error(
    `\nRoutes without a bundle budget (add them to config/bundle-budgets.json):\n${unmatched.map((r) => `  ${r}`).join("\n")}`,
  );
}
if (violations.length > 0) {
  console.error(
    `\n${violations.length} route(s) over budget:\n${violations
      .map(
        (r) =>
          `  ${r.route}: ${(r.gzipBytes / 1000).toFixed(1)} KB gzip > ${r.budgetKb} KB`,
      )
      .join("\n")}`,
  );
}
if (unmatched.length > 0 || violations.length > 0) {
  process.exit(1);
}
console.log(`\nAll ${rows.length} routes are within their bundle budget.`);
