// @vitest-environment node
import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

import { afterEach, describe, expect, it } from "vitest";

import {
  computeRouteSizes,
  evaluateBudgets,
  findBudget,
} from "./bundle-budgets-lib.mjs";

const SCRIPT = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "check-bundle-budgets.mjs",
);
const tempDirs = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

// Deterministic, poorly compressible filler of an exact length.
function filler(length) {
  let state = 12345;
  const bytes = Buffer.alloc(length);
  for (let i = 0; i < length; i += 1) {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    bytes[i] = state >> 16;
  }
  return bytes;
}

const budgets = {
  compression: "gzip-9",
  groups: [
    { name: "marketing", routes: ["/[locale]", "/[locale]/*"], maxKb: 10 },
  ],
  routes: { "/[locale]/pricing": 3 },
};

describe("computeRouteSizes", () => {
  it("sums raw and gzip-9 bytes of the first-load chunks per route", () => {
    const files = { a: filler(2000), b: filler(500) };
    const sizes = computeRouteSizes(
      [
        { route: "/x", firstLoadChunkPaths: ["a", "b"] },
        { route: "/y", firstLoadChunkPaths: ["a"] },
      ],
      (chunkPath) => files[chunkPath],
    );
    const gzip = (buffer) => gzipSync(buffer, { level: 9 }).length;
    expect(sizes[0]).toEqual({
      route: "/x",
      chunks: 2,
      rawBytes: 2500,
      gzipBytes: gzip(files.a) + gzip(files.b),
    });
    expect(sizes[1].gzipBytes).toBe(gzip(files.a));
  });

  it("reads each chunk once even when routes share it", () => {
    let reads = 0;
    computeRouteSizes(
      [
        { route: "/x", firstLoadChunkPaths: ["a"] },
        { route: "/y", firstLoadChunkPaths: ["a"] },
      ],
      () => {
        reads += 1;
        return filler(10);
      },
    );
    expect(reads).toBe(1);
  });

  it("fails loudly on a missing chunk or malformed stats", () => {
    expect(() =>
      computeRouteSizes(
        [{ route: "/x", firstLoadChunkPaths: ["gone"] }],
        () => {
          throw new Error("ENOENT: gone");
        },
      ),
    ).toThrow("ENOENT");
    expect(() => computeRouteSizes({}, () => Buffer.alloc(0))).toThrow(
      "must be an array",
    );
  });

  it("treats a route without chunks as empty", () => {
    expect(computeRouteSizes([{ route: "/x" }], () => Buffer.alloc(0))).toEqual(
      [{ route: "/x", chunks: 0, rawBytes: 0, gzipBytes: 0 }],
    );
  });
});

describe("evaluateBudgets", () => {
  it("passes a route within its group budget", () => {
    const result = evaluateBudgets(
      [{ route: "/[locale]", gzipBytes: 9_999 }],
      budgets,
    );
    expect(result.violations).toEqual([]);
    expect(result.unmatched).toEqual([]);
    expect(result.rows[0]).toMatchObject({
      budgetName: "marketing",
      budgetKb: 10,
    });
  });

  it("fails a route over budget", () => {
    const result = evaluateBudgets(
      [{ route: "/[locale]/security", gzipBytes: 10_001 }],
      budgets,
    );
    expect(result.violations.map((row) => row.route)).toEqual([
      "/[locale]/security",
    ]);
  });

  it("lets a per-route entry override the group and fails when lowered", () => {
    const sizes = [{ route: "/[locale]/pricing", gzipBytes: 3_500 }];
    expect(evaluateBudgets(sizes, budgets).violations).toHaveLength(1);
    const relaxed = { ...budgets, routes: { "/[locale]/pricing": 4 } };
    expect(evaluateBudgets(sizes, relaxed).violations).toEqual([]);
  });

  it("reports routes without a budget as unmatched", () => {
    const result = evaluateBudgets(
      [{ route: "/brand-new-route", gzipBytes: 1 }],
      budgets,
    );
    expect(result.unmatched).toEqual(["/brand-new-route"]);
    expect(result.rows).toEqual([]);
  });

  it("matches wildcards literally apart from * and escapes brackets", () => {
    expect(findBudget("/[locale]/a/b", budgets)?.name).toBe("marketing");
    expect(findBudget("/l/a", budgets)).toBeNull();
    expect(findBudget("/x", {})).toBeNull();
  });
});

describe("scripts/check-bundle-budgets.mjs", () => {
  function setup({ stats, budgetKb }) {
    const dir = mkdtempSync(path.join(tmpdir(), "bundle-budgets-"));
    tempDirs.push(dir);
    const chunk = path.join(dir, "chunk.js");
    writeFileSync(chunk, filler(4000));
    if (stats !== null) {
      mkdirSync(path.join(dir, "diagnostics"));
      writeFileSync(
        path.join(dir, "diagnostics/route-bundle-stats.json"),
        JSON.stringify([{ route: "/app-route", firstLoadChunkPaths: [chunk] }]),
      );
    }
    const budgetsFile = path.join(dir, "budgets.json");
    writeFileSync(
      budgetsFile,
      JSON.stringify({
        compression: "gzip-9",
        groups: [{ name: "app", routes: ["/app-route"], maxKb: budgetKb }],
      }),
    );
    const result = spawnSync(process.execPath, [SCRIPT], {
      encoding: "utf8",
      env: {
        ...process.env,
        NEXT_DIST_DIR: dir,
        BUNDLE_BUDGETS_FILE: budgetsFile,
      },
    });
    return { dir, result };
  }

  it("passes within budget and writes bundle-report.json", () => {
    const { dir, result } = setup({ stats: true, budgetKb: 10 });
    expect(result.status).toBe(0);
    expect(result.stdout).toContain(
      "All 1 routes are within their bundle budget",
    );
    const report = JSON.parse(
      readFileSync(path.join(dir, "bundle-report.json"), "utf8"),
    );
    expect(report.routes[0]).toMatchObject({
      route: "/app-route",
      budgetKb: 10,
    });
  });

  it("exits 1 when the budget is artificially lowered", () => {
    const { result } = setup({ stats: true, budgetKb: 1 });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("1 route(s) over budget");
    expect(result.stderr).toContain("/app-route");
  });

  it("exits 1 when the stats file is missing", () => {
    const { result } = setup({ stats: null, budgetKb: 10 });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("route-bundle-stats.json");
  });

  it("exits 1 on a route without a budget", () => {
    const { dir, result } = setup({ stats: true, budgetKb: 10 });
    writeFileSync(
      path.join(dir, "budgets.json"),
      JSON.stringify({ groups: [], routes: {} }),
    );
    const rerun = spawnSync(process.execPath, [SCRIPT], {
      encoding: "utf8",
      env: {
        ...process.env,
        NEXT_DIST_DIR: dir,
        BUNDLE_BUDGETS_FILE: path.join(dir, "budgets.json"),
      },
    });
    expect(result.status).toBe(0);
    expect(rerun.status).toBe(1);
    expect(rerun.stderr).toContain("Routes without a bundle budget");
  });

  it("exits 1 when a chunk file cannot be read", () => {
    const { dir } = setup({ stats: true, budgetKb: 10 });
    writeFileSync(
      path.join(dir, "diagnostics/route-bundle-stats.json"),
      JSON.stringify([
        {
          route: "/app-route",
          firstLoadChunkPaths: [path.join(dir, "gone.js")],
        },
      ]),
    );
    const rerun = spawnSync(process.execPath, [SCRIPT], {
      encoding: "utf8",
      env: {
        ...process.env,
        NEXT_DIST_DIR: dir,
        BUNDLE_BUDGETS_FILE: path.join(dir, "budgets.json"),
      },
    });
    expect(rerun.status).toBe(1);
    expect(rerun.stderr).toContain("Cannot measure route bundles");
  });

  it("exits 1 when the budgets file is unreadable", () => {
    const { dir } = setup({ stats: true, budgetKb: 10 });
    const rerun = spawnSync(process.execPath, [SCRIPT], {
      encoding: "utf8",
      env: {
        ...process.env,
        NEXT_DIST_DIR: dir,
        BUNDLE_BUDGETS_FILE: path.join(dir, "missing.json"),
      },
    });
    expect(rerun.status).toBe(1);
    expect(rerun.stderr).toContain("Cannot read");
  });
});
