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
    expect(links.changelog).toBe(PUBLIC_ROUTE_PATHS.changelog);
    expect(links.contact).toBe(PUBLIC_ROUTE_PATHS.contact);
    expect(links.securityContact).toBe(PUBLIC_ROUTE_PATHS.contact);
    expect(links.status).toBe(PUBLIC_ROUTE_PATHS.status);
  });

  it("uses internal legal route defaults when no env overrides are set", () => {
    const links = resolvePublicSiteLinks();

    expect(links.privacy).toBe(PUBLIC_ROUTE_PATHS.privacy);
    expect(links.terms).toBe(PUBLIC_ROUTE_PATHS.terms);
    expect(links.cookies).toBe(PUBLIC_ROUTE_PATHS.cookies);
    expect(links.dpa).toBe(PUBLIC_ROUTE_PATHS.dpa);
    expect(links.subprocessors).toBe(PUBLIC_ROUTE_PATHS.subprocessors);
    expect(links.acceptableUse).toBe(PUBLIC_ROUTE_PATHS.acceptableUse);
    expect(links.securityDisclosure).toBe(
      PUBLIC_ROUTE_PATHS.securityDisclosure,
    );
  });

  it("accepts env-driven legal link overrides", () => {
    process.env.NEXT_PUBLIC_PUBLIC_PRIVACY_URL =
      "https://legal.example.com/privacy";
    process.env.NEXT_PUBLIC_PUBLIC_TERMS_URL =
      "https://legal.example.com/terms";
    process.env.NEXT_PUBLIC_PUBLIC_SECURITY_DISCLOSURE_URL =
      "https://legal.example.com/security";

    const links = resolvePublicSiteLinks();

    expect(links.privacy).toBe("https://legal.example.com/privacy");
    expect(links.terms).toBe("https://legal.example.com/terms");
    expect(links.securityDisclosure).toBe("https://legal.example.com/security");
  });

  it("prefers new NEXT_PUBLIC_PUBLIC_* overrides", () => {
    process.env.NEXT_PUBLIC_PUBLIC_PRODUCT_URL = "/product-custom";
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";
    process.env.NEXT_PUBLIC_PUBLIC_SECURITY_CONTACT_URL =
      "https://security.example.com/review";

    const links = resolvePublicSiteLinks();

    expect(links.product).toBe("/product-custom");
    expect(links.requestDemo).toBe("https://demo.example.com");
    expect(links.securityContact).toBe("https://security.example.com/review");
  });

  it("normalizes support email into a mailto security contact link", () => {
    process.env.NEXT_PUBLIC_SUPPORT_EMAIL = "security@example.com";

    const links = resolvePublicSiteLinks();

    expect(links.securityContact).toBe("mailto:security@example.com");
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
    expect(footerGroups[0]?.items.map((item) => item.label)).toContain(
      "Changelog",
    );
  });
});
