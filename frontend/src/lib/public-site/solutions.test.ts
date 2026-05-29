import { describe, expect, it } from "vitest";

import {
  getSolutionAudienceBySlug,
  SOLUTION_AUDIENCES,
  SOLUTION_OVERVIEW_FLOW_STEPS,
  SOLUTION_ROLE_NAV,
} from "@/lib/public-site/solutions";

describe("public solutions model", () => {
  it("defines nine unique solution audiences with unique routes", () => {
    expect(SOLUTION_AUDIENCES).toHaveLength(9);

    const slugs = new Set(SOLUTION_AUDIENCES.map((solution) => solution.slug));
    const routes = new Set(
      SOLUTION_AUDIENCES.map((solution) => solution.routePath),
    );

    expect(slugs.size).toBe(9);
    expect(routes.size).toBe(9);
  });

  it("maps role navigation to every solution route", () => {
    expect(SOLUTION_ROLE_NAV).toHaveLength(SOLUTION_AUDIENCES.length);
    for (const item of SOLUTION_ROLE_NAV) {
      expect(
        SOLUTION_AUDIENCES.some((solution) => solution.routePath === item.href),
      ).toBe(true);
    }
  });

  it("provides lookup by slug and workflow overview steps", () => {
    const solution = getSolutionAudienceBySlug("legal");
    expect(solution?.routePath).toBe("/solutions/legal");
    expect(SOLUTION_OVERVIEW_FLOW_STEPS.length).toBeGreaterThanOrEqual(4);
  });
});
