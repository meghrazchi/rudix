import { describe, expect, it } from "vitest";
import {
  DEFAULT_REPORT_FILTERS,
  REPORT_SECTIONS,
  canViewReportSection,
  getVisibleReportSections,
  parseReportFilters,
  serializeReportFilters,
} from "@/lib/reports";

describe("report role visibility", () => {
  it("limits normal users to personal report sections", () => {
    expect(
      getVisibleReportSections("member").map((section) => section.id),
    ).toEqual([
      "overview",
      "answer-quality",
      "usage-adoption",
      "feedback-issues",
    ]);
    expect(
      getVisibleReportSections("viewer").map((section) => section.id),
    ).toEqual([
      "overview",
      "answer-quality",
      "usage-adoption",
      "feedback-issues",
    ]);
  });

  it("allows reviewers to see review sections but not access reports", () => {
    const ids = getVisibleReportSections("reviewer").map(
      (section) => section.id,
    );
    expect(ids).toContain("source-health");
    expect(ids).toContain("knowledge-gaps");
    expect(ids).not.toContain("permissions-access");
  });

  it("allows admins and owners to access every report section", () => {
    expect(getVisibleReportSections("admin")).toHaveLength(
      REPORT_SECTIONS.length,
    );
    expect(getVisibleReportSections("owner")).toHaveLength(
      REPORT_SECTIONS.length,
    );
  });

  it("denies direct section access when the role is not allowed", () => {
    const accessReport = REPORT_SECTIONS.find(
      (section) => section.id === "permissions-access",
    )!;
    expect(canViewReportSection("member", accessReport)).toBe(false);
    expect(canViewReportSection("admin", accessReport)).toBe(true);
  });
});

describe("global report filters", () => {
  it("uses stable defaults when the URL has no filters", () => {
    expect(parseReportFilters(new URLSearchParams())).toEqual(
      DEFAULT_REPORT_FILTERS,
    );
  });

  it("round-trips shared filter state and omits defaults", () => {
    const filters = {
      ...DEFAULT_REPORT_FILTERS,
      date: "90d",
      team: "mine",
      language: "de",
      confidence: "low",
    };
    const params = serializeReportFilters(filters);
    expect(params.has("workspace")).toBe(false);
    expect(parseReportFilters(params)).toEqual(filters);
  });
});
