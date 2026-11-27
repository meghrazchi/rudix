// Pure helpers for the bundle budget gate (R07-03).
// computeRouteSizes: first-load JS size per route from Next's
// route-bundle-stats.json; evaluateBudgets: compares them with the budgets.
import { gzipSync } from "node:zlib";

const KB = 1000;

/**
 * @param {Array<{route: string, firstLoadChunkPaths: string[]}>} stats
 * @param {(chunkPath: string) => Buffer} readFile returns the chunk bytes
 * @returns {Array<{route: string, chunks: number, rawBytes: number, gzipBytes: number}>}
 */
export function computeRouteSizes(stats, readFile) {
  if (!Array.isArray(stats)) {
    throw new Error("route-bundle-stats.json must be an array of routes");
  }
  const cache = new Map();
  const measure = (chunkPath) => {
    let entry = cache.get(chunkPath);
    if (!entry) {
      const bytes = readFile(chunkPath);
      entry = {
        raw: bytes.length,
        gzip: gzipSync(bytes, { level: 9 }).length,
      };
      cache.set(chunkPath, entry);
    }
    return entry;
  };
  return stats.map((item) => {
    let rawBytes = 0;
    let gzipBytes = 0;
    const chunkPaths = item.firstLoadChunkPaths ?? [];
    for (const chunkPath of chunkPaths) {
      const entry = measure(chunkPath);
      rawBytes += entry.raw;
      gzipBytes += entry.gzip;
    }
    return {
      route: item.route,
      chunks: chunkPaths.length,
      rawBytes,
      gzipBytes,
    };
  });
}

function patternToRegExp(pattern) {
  const escaped = pattern
    .split("*")
    .map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${escaped}$`);
}

/**
 * Budget lookup: a `routes` entry wins, then the first matching group.
 * `*` in a pattern matches any characters.
 * @returns {{name: string, maxKb: number} | null}
 */
export function findBudget(route, budgets) {
  for (const [pattern, maxKb] of Object.entries(budgets.routes ?? {})) {
    if (patternToRegExp(pattern).test(route)) {
      return { name: pattern, maxKb };
    }
  }
  for (const group of budgets.groups ?? []) {
    if (group.routes.some((pattern) => patternToRegExp(pattern).test(route))) {
      return { name: group.name, maxKb: group.maxKb };
    }
  }
  return null;
}

/**
 * @returns {{rows: object[], violations: object[], unmatched: string[]}}
 */
export function evaluateBudgets(sizes, budgets) {
  const rows = [];
  const violations = [];
  const unmatched = [];
  for (const size of sizes) {
    const budget = findBudget(size.route, budgets);
    if (!budget) {
      unmatched.push(size.route);
      continue;
    }
    const row = { ...size, budgetName: budget.name, budgetKb: budget.maxKb };
    rows.push(row);
    if (size.gzipBytes > budget.maxKb * KB) {
      violations.push(row);
    }
  }
  return { rows, violations, unmatched };
}
