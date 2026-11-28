import { describe, expect, it } from "vitest";

import ar from "./messages/ar.json";
import de from "./messages/de.json";
import en from "./messages/en.json";
import es from "./messages/es.json";
import fa from "./messages/fa.json";
import fr from "./messages/fr.json";

/**
 * R07-12: translated messages keep the placeholders, ICU plural arguments and
 * rich-text tags of the English source, so a translation cannot silently drop
 * `{count}` or `<strong>`.
 */
const LOCALES = { de, es, fr, ar, fa } as const;

// Subtrees translated by R07-12 (trust panel, feedback/share modals, activity,
// evaluations sub-panels, state components).
const COVERED: string[][] = [
  ["chat", "trustPanel"],
  ["chat", "feedback"],
  ["chat", "share"],
  ["chat", "activity"],
  ["states"],
  ["evaluations", "chunkingComparison"],
  ["evaluations", "multilingual"],
  ["evaluations", "runDetail"],
  ["evaluations", "setsSection"],
  ["evaluations", "dialogs"],
  ["evaluations", "modelProfiles"],
  ["evaluations", "abTest"],
  ["evaluations", "runComparison"],
  ["evaluations", "qualityGate"],
  ["evaluations", "datasetBuilder"],
];

type Tree = { [key: string]: Tree | string };

function leaves(node: Tree | string, prefix: string): Map<string, string> {
  const out = new Map<string, string>();
  if (typeof node === "string") {
    out.set(prefix, node);
    return out;
  }
  for (const [key, value] of Object.entries(node)) {
    for (const [k, v] of leaves(value, `${prefix}.${key}`)) out.set(k, v);
  }
  return out;
}

function pick(root: Tree, path: string[]): Tree | string {
  let node: Tree | string = root;
  for (const segment of path) {
    node = (node as Tree)[segment];
  }
  return node;
}

function placeholders(rawMessage: string): string[] {
  // Drop plural/select branch bodies ("one {# case}") so only arguments remain. Repeat
  // until nothing changes, so a removal cannot leave a new branch body behind.
  const branchBody = /\b(?:zero|one|two|few|many|other|=\d+)\s*\{[^{}]*\}/g;
  let message = rawMessage;
  let previous: string;
  do {
    previous = message;
    message = message.replace(branchBody, "");
  } while (message !== previous);
  const args = [...message.matchAll(/\{\s*([A-Za-z_]\w*)\s*[,}]/g)].map(
    (m) => m[1],
  );
  const tags = [...message.matchAll(/<\/?([A-Za-z]+)>/g)].map(
    (m) => `<${m[1]}>`,
  );
  return [...new Set([...args, ...tags])].sort();
}

describe("translated message placeholders (R07-12)", () => {
  for (const path of COVERED) {
    const name = path.join(".");
    const source = leaves(pick(en as unknown as Tree, path), name);

    it(`${name} exists and is non-empty`, () => {
      expect(source.size).toBeGreaterThan(0);
    });

    for (const [locale, messages] of Object.entries(LOCALES)) {
      it(`${name} keeps English placeholders in ${locale}`, () => {
        const translated = leaves(
          pick(messages as unknown as Tree, path),
          name,
        );
        for (const [key, value] of source) {
          expect(translated.get(key), key).toBeDefined();
          expect(placeholders(translated.get(key) ?? ""), key).toEqual(
            placeholders(value),
          );
        }
      });
    }
  }
});
