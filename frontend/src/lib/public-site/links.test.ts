import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  PUBLIC_ROUTE_PATHS,
  buildFooterLinkGroups,
  buildPrimaryNavItems,
  resolvePublicSiteLinks,
} from "@/lib/public-site/links";

const originalEnv = { ...process.env };

beforeEach(() => {
  process.env = { ...originalEnv };
});

afterEach(() => {
  process.env = { ...originalEnv };
});

describe("public site links", () => {
  it("uses internal route defaults when no env overrides are set", () => {
    const links = resolvePublicSiteLinks();

    expect(links.home).toBe(PUBLIC_ROUTE_PATHS.home);
    expect(links.product).toBe(PUBLIC_ROUTE_PATHS.product);
    expect(links.solutions).toBe(PUBLIC_ROUTE_PATHS.solutions);
    expect(links.security).toBe(PUBLIC_ROUTE_PATHS.security);
    expect(links.pricing).toBe(PUBLIC_ROUTE_PATHS.pricing);
    expect(links.contact).toBe(PUBLIC_ROUTE_PATHS.contact);
    expect(links.status).toBe(PUBLIC_ROUTE_PATHS.status);
  });

  it("prefers new NEXT_PUBLIC_PUBLIC_* overrides", () => {
    process.env.NEXT_PUBLIC_PUBLIC_PRODUCT_URL = "/product-custom";
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    const links = resolvePublicSiteLinks();

    expect(links.product).toBe("/product-custom");
    expect(links.requestDemo).toBe("https://demo.example.com");
  });

  it("builds a full primary nav and footer link groups", () => {
    const links = resolvePublicSiteLinks();

    const navItems = buildPrimaryNavItems(links);
    expect(navItems.map((item) => item.label)).toEqual([
      "Product",
      "Solutions",
      "Security",
      "Pricing",
    ]);

    const footerGroups = buildFooterLinkGroups(links);
    expect(footerGroups.length).toBe(3);
    expect(footerGroups[0]?.heading).toBe("Product");
    expect(footerGroups[1]?.heading).toBe("Solutions");
    expect(footerGroups[2]?.heading).toBe("Company & Support");
  });
});
