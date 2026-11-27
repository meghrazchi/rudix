#!/usr/bin/env node
// Collects the Material Symbols names used in src/ and keeps
// config/material-symbols.json (the self-hosted icon subset, R07-04) in sync.
//
//   node scripts/material-symbols-subset.mjs           rewrite the list
//   node scripts/material-symbols-subset.mjs --check   fail on unlisted names
//
// After the list changes, regenerate the font file; see
// docs/ frontend README "Assets, error boundaries and Web Vitals".

import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(root, "src");
const listPath = join(root, "config", "material-symbols.json");

const NAME = "[a-z][a-z0-9]*(?:_[a-z0-9]+)*";

// Prop and object-key forms that carry an icon name.
const PROP_PATTERNS = [
  new RegExp(`<\\w*Icon\\b[^>]*?\\bname=\\{?"(${NAME})"`, "g"),
  new RegExp(
    `\\b(?:icon|iconName|symbol|leadingIcon|trailingIcon)=\\{?"(${NAME})"`,
    "g",
  ),
  new RegExp(
    `\\b(?:icon|iconName|symbol|materialIcon)\\??:\\s*"(${NAME})"`,
    "g",
  ),
];

/** @param {string} dir @returns {string[]} */
function sourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (
      /\.(tsx?|jsx?)$/.test(entry.name) &&
      !/\.test\.[tj]sx?$/.test(entry.name)
    ) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Names used by one source file.
 * @param {string} text
 * @returns {Set<string>}
 */
export function namesInSource(text) {
  const names = new Set();
  for (const pattern of PROP_PATTERNS) {
    for (const m of text.matchAll(pattern)) names.add(m[1]);
  }
  // Literal or expression text inside an element carrying the icon class.
  const element = /material-symbols-outlined(?:=>|[^>])*>([^<]*)</g;
  for (const m of text.matchAll(element)) {
    for (const lit of m[1].matchAll(new RegExp(`(?<!=\\s*)"(${NAME})"`, "g")))
      names.add(lit[1]);
    const plain = m[1].trim();
    if (new RegExp(`^${NAME}$`).test(plain)) names.add(plain);
  }
  return names;
}

/** @returns {string[]} */
export function collectNames() {
  const all = new Set();
  for (const file of sourceFiles(srcDir)) {
    for (const n of namesInSource(readFileSync(file, "utf8"))) all.add(n);
  }
  return [...all].sort();
}

function main() {
  const check = process.argv.includes("--check");
  const used = collectNames();
  if (check) {
    const listed = new Set(JSON.parse(readFileSync(listPath, "utf8")));
    const missing = used.filter((n) => !listed.has(n));
    if (missing.length > 0) {
      console.error(
        `Icons used in ${relative(root, srcDir)} but missing from config/material-symbols.json:\n  ${missing.join(
          "\n  ",
        )}\nRun "node scripts/material-symbols-subset.mjs" and regenerate the font subset.`,
      );
      process.exit(1);
    }
    console.log(
      `icons:check ok (${used.length} names used, ${listed.size} listed)`,
    );
    return;
  }
  // Names reached only through maps or helper returns cannot be detected by
  // pattern, so existing entries are kept (union). Remove a name by hand.
  const existing = JSON.parse(readFileSync(listPath, "utf8"));
  const merged = [...new Set([...existing, ...used])].sort();
  writeFileSync(listPath, `${JSON.stringify(merged, null, 2)}\n`);
  console.log(`Wrote ${merged.length} names to config/material-symbols.json`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
