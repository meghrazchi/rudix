import { describe, expect, it } from "vitest";

import { buildPublicMetadata } from "@/lib/public-site/seo";

describe("public site metadata", () => {
  it("builds metadata with canonical and social fields", () => {
    const metadata = buildPublicMetadata({
      title: "Product | Rudix",
      description: "Product overview",
      path: "/product",
    });

    expect(metadata.title).toBe("Product | Rudix");
    expect(metadata.description).toBe("Product overview");
    expect(metadata.alternates?.canonical).toBe("/product");
    const openGraph = metadata.openGraph as
      | { type?: string; url?: string }
      | undefined;
    const twitter = metadata.twitter as { card?: string } | undefined;

    expect(openGraph?.type).toBe("website");
    expect(openGraph?.url).toContain("/product");
    expect(twitter?.card).toBe("summary_large_image");
  });

  it("supports no-index pages", () => {
    const metadata = buildPublicMetadata({
      title: "Status | Rudix",
      description: "Status page",
      path: "/status",
      noIndex: true,
    });

    const robots = metadata.robots as
      | { index?: boolean; follow?: boolean }
      | undefined;

    expect(robots?.index).toBe(false);
    expect(robots?.follow).toBe(false);
  });
});
