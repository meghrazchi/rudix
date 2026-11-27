// Fails when an API client module declares a response-shaped type by hand (R07-05).
//
// Response, item, record, summary, detail, entry, result, payload and request types must be
// derived from the generated OpenAPI schema (`Schemas[...]`, `components[...]`,
// `operations[...]`). Client-only view models go in config/api-handwritten-allowlist.json
// with a reason.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const apiDir = path.join(root, "src", "lib", "api");
const allowlistPath = path.join(
  root,
  "config",
  "api-handwritten-allowlist.json",
);

const INFRA = new Set([
  "request.ts",
  "session.ts",
  "auth.ts",
  "errors.ts",
  "query.ts",
  "index.ts",
  "web-vitals.ts",
  "events.ts",
  "schema-helpers.ts",
]);
const SUFFIX =
  /(Response|Item|Record|Summary|Detail|Entry|Result|Payload|Request)$/;
const REFERENCES = /(Schemas\[|components\[|operations\[)/;
const DECLARATION = /^export (?:type (\w+)\s*(?:<[^>]*>)?\s*=|interface (\w+))/;

/** Returns the text of a declaration starting at `start` up to the next top-level declaration. */
function declarationBody(lines, start) {
  let end = start + 1;
  while (
    end < lines.length &&
    !/^(export |type |interface |function |const |async |\/\/|\/\*)/.test(
      lines[end],
    )
  ) {
    end += 1;
  }
  return lines.slice(start, end).join("\n");
}

/**
 * Names of non-exported helper aliases (`type Base = Schemas["X"]`) whose body reaches the
 * generated schema. An exported declaration that builds on one of them counts as derived.
 */
function schemaAliasNames(lines) {
  const aliases = new Set();
  lines.forEach((line, index) => {
    const match = /^type (\w+)\s*(?:<[^>]*>)?\s*=/.exec(line);
    if (match && REFERENCES.test(declarationBody(lines, index)))
      aliases.add(match[1]);
  });
  return aliases;
}

export function findViolations(files, allowlist) {
  const violations = [];
  for (const { name: file, text } of files) {
    const lines = text.split("\n");
    const aliases = schemaAliasNames(lines);
    lines.forEach((line, index) => {
      const match = DECLARATION.exec(line);
      if (!match) return;
      const name = match[1] ?? match[2];
      if (!SUFFIX.test(name)) return;
      const body = declarationBody(lines, index);
      if (REFERENCES.test(body)) return;
      if ([...aliases].some((alias) => new RegExp(`\\b${alias}\\b`).test(body)))
        return;
      if (
        Object.hasOwn(allowlist, name) ||
        Object.hasOwn(allowlist, `${file}:${name}`)
      )
        return;
      violations.push(`${file}:${index + 1} ${name}`);
    });
  }
  return violations;
}

function main() {
  const allowlist = JSON.parse(readFileSync(allowlistPath, "utf8"));
  const files = readdirSync(apiDir)
    .filter(
      (f) => f.endsWith(".ts") && !f.endsWith(".test.ts") && !INFRA.has(f),
    )
    .map((f) => ({
      name: f,
      text: readFileSync(path.join(apiDir, f), "utf8"),
    }));
  const violations = findViolations(files, allowlist);
  if (violations.length > 0) {
    console.error(
      "Hand-written API types found. Derive them from generated/schema.d.ts:",
    );
    for (const v of violations) console.error(`  ${v}`);
    console.error(
      "Or add a client-only view model to config/api-handwritten-allowlist.json.",
    );
    process.exit(1);
  }
  console.log(
    `API client types derive from the generated schema (${files.length} modules).`,
  );
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
