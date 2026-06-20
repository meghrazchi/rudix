import type { MetadataRoute } from "next";

import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";

const PRIVATE_PATH_PREFIXES = [
  "/dashboard",
  "/documents",
  "/graph",
  "/chat",
  "/evaluations",
  "/rag-pipeline",
  "/settings",
  "/admin",
  "/workspace",
  "/user",
];

export default function robots(): MetadataRoute.Robots {
  const baseUrl = resolvePublicSiteBaseUrl();

  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: PRIVATE_PATH_PREFIXES,
      },
    ],
    sitemap: new URL("/sitemap.xml", baseUrl).toString(),
  };
}
