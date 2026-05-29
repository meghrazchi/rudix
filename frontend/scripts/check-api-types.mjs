#!/usr/bin/env node
/**
 * Verifies that src/lib/api/generated/schema.d.ts is up to date with openapi.json.
 *
 * Regenerates types to a temporary file and diffs against the committed file.
 * Exits non-zero and prints guidance if they differ.
 */
import { execSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const root = new URL("..", import.meta.url).pathname;
const schemaPath = join(root, "src/lib/api/generated/schema.d.ts");
const openapiPath = join(root, "openapi.json");
const tmpPath = join(tmpdir(), `schema-check-${Date.now()}.d.ts`);

try {
  execSync(`npx openapi-typescript "${openapiPath}" -o "${tmpPath}"`, {
    stdio: "pipe",
    cwd: root,
  });

  const committed = readFileSync(schemaPath, "utf8");
  const regenerated = readFileSync(tmpPath, "utf8");

  if (committed === regenerated) {
    console.log("API types are up to date.");
    process.exit(0);
  }

  console.error(
    "Generated API types are stale.\n" +
      "Run `npm run api:generate` (or `npm run api:update-schema` to also refresh openapi.json) and commit the result.\n\n" +
      "Diff (committed vs regenerated):",
  );

  // Print a simple line diff for visibility in CI logs.
  const committedLines = committed.split("\n");
  const regeneratedLines = regenerated.split("\n");
  const maxLen = Math.max(committedLines.length, regeneratedLines.length);
  let shown = 0;
  for (let i = 0; i < maxLen && shown < 30; i++) {
    const a = committedLines[i] ?? "";
    const b = regeneratedLines[i] ?? "";
    if (a !== b) {
      console.error(`  line ${i + 1}:`);
      if (a) console.error(`  - ${a}`);
      if (b) console.error(`  + ${b}`);
      shown++;
    }
  }
  if (shown === 30) {
    console.error("  ... (truncated)");
  }

  process.exit(1);
} finally {
  try {
    rmSync(tmpPath, { force: true });
  } catch {
    // ignore cleanup failure
  }
}
