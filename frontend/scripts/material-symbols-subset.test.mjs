// @vitest-environment node
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { collectNames, namesInSource } from "./material-symbols-subset.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));

describe("namesInSource", () => {
  it("finds names in props, object keys and element text", () => {
    const names = namesInSource(`
      <SiteIcon name="shield_lock" />
      <Button icon="add" />
      const x = { icon: "search" };
      <span className="material-symbols-outlined">close</span>
      <span className="material-symbols-outlined">{ok ? "check" : "error"}</span>
    `);
    expect([...names].sort()).toEqual([
      "add",
      "check",
      "close",
      "error",
      "search",
      "shield_lock",
    ]);
  });

  it("ignores form field names and comparisons", () => {
    const names = namesInSource(`
      <input name="policy_name" />
      <span className="material-symbols-outlined">{t === "pdf" ? "picture_as_pdf" : "description"}</span>
    `);
    expect([...names].sort()).toEqual(["description", "picture_as_pdf"]);
  });
});

describe("config/material-symbols.json", () => {
  it("lists every name the source uses, sorted and unique", () => {
    const listed = JSON.parse(
      readFileSync(path.join(here, "../config/material-symbols.json"), "utf8"),
    );
    expect(listed).toEqual([...new Set(listed)].sort());
    for (const name of collectNames()) expect(listed).toContain(name);
  });
});
