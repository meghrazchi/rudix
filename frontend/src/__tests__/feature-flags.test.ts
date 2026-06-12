import { describe, expect, it } from "vitest";

import {
  ALL_FLAG_NAMES,
  FLAG_LABELS,
  type FeatureFlagName,
} from "@/lib/api/feature-flags";

describe("feature-flags API client", () => {
  it("ALL_FLAG_NAMES is non-empty and contains expected flags", () => {
    expect(ALL_FLAG_NAMES.length).toBeGreaterThan(0);
    expect(ALL_FLAG_NAMES).toContain("agents");
    expect(ALL_FLAG_NAMES).toContain("mcp");
    expect(ALL_FLAG_NAMES).toContain("connectors");
    expect(ALL_FLAG_NAMES).toContain("evaluations");
  });

  it("ALL_FLAG_NAMES has no duplicates", () => {
    expect(new Set(ALL_FLAG_NAMES).size).toBe(ALL_FLAG_NAMES.length);
  });

  it("every flag in ALL_FLAG_NAMES has a label in FLAG_LABELS", () => {
    for (const name of ALL_FLAG_NAMES) {
      expect(FLAG_LABELS[name as FeatureFlagName]).toBeTruthy();
    }
  });

  it("FLAG_LABELS values are non-empty strings", () => {
    for (const [, label] of Object.entries(FLAG_LABELS)) {
      expect(typeof label).toBe("string");
      expect(label.length).toBeGreaterThan(0);
    }
  });
});
