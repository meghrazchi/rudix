import { describe, expect, it } from "vitest";

import staticPublicRoutes from "../../../config/static-public-routes.json";
import { PUBLIC_ROUTE_PATHS } from "./links";
import { PUBLIC_SITEMAP_PATHS } from "./sitemap";

describe("config/static-public-routes.json", () => {
  it("lists every sitemap path except the live status page", () => {
    const expected = PUBLIC_SITEMAP_PATHS.filter(
      (path) => path !== PUBLIC_ROUTE_PATHS.status,
    );
    expect(staticPublicRoutes).toEqual(expected);
  });

  it("has no duplicates and only root-relative paths", () => {
    expect(new Set(staticPublicRoutes).size).toBe(staticPublicRoutes.length);
    for (const path of staticPublicRoutes) {
      expect(path.startsWith("/")).toBe(true);
    }
  });
});
