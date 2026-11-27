// @vitest-environment node
import { spawnSync } from "node:child_process";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { findViolations } from "./check-api-handwritten-types.mjs";

const SCRIPT = path.join(__dirname, "check-api-handwritten-types.mjs");

function check(text: string, allowlist: Record<string, string> = {}): string[] {
  return findViolations([{ name: "sample.ts", text }], allowlist) as string[];
}

describe("check-api-handwritten-types", () => {
  it("flags a hand-written response type", () => {
    const violations = check(
      "export type WidgetResponse = {\n  id: string;\n};\n",
    );
    expect(violations).toEqual(["sample.ts:1 WidgetResponse"]);
  });

  it("flags an interface with a checked suffix", () => {
    expect(
      check("export interface WidgetItem {\n  id: string;\n}\n"),
    ).toHaveLength(1);
  });

  it("ignores names without a checked suffix", () => {
    expect(check("export type WidgetStatus = 'a' | 'b';\n")).toEqual([]);
  });

  it("accepts declarations derived from the generated schema", () => {
    const text = [
      'export type A = Schemas["A"];',
      'export type BResponse = Omit<Schemas["B"], "x"> & {',
      "  x: string;",
      "};",
      'export type CRequest = components["schemas"]["C"];',
      'export type DResult = operations["op"]["responses"][200];',
    ].join("\n");
    expect(check(text)).toEqual([]);
  });

  it("accepts declarations built on a local alias of the schema", () => {
    const text = [
      'type Base = Schemas["Thing"];',
      "export type ThingResponse = Omit<Base, 'x'> & { x: string };",
    ].join("\n");
    expect(check(text)).toEqual([]);
  });

  it("does not treat an exported hand-written type as a schema alias", () => {
    const text = [
      'export type Derived = Schemas["Thing"];',
      "export type OtherResponse = { item: Derived };",
    ].join("\n");
    expect(check(text)).toEqual(["sample.ts:2 OtherResponse"]);
  });

  it("honours the allowlist by name and by file", () => {
    const text = "export type WidgetResponse = {\n  id: string;\n};\n";
    expect(check(text, { WidgetResponse: "view model" })).toEqual([]);
    expect(check(text, { "sample.ts:WidgetResponse": "view model" })).toEqual(
      [],
    );
    expect(check(text, { OtherResponse: "view model" })).toHaveLength(1);
  });

  it("passes on the repository's API modules", () => {
    const result = spawnSync("node", [SCRIPT], { encoding: "utf8" });
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
  });
});
