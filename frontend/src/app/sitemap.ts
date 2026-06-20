import type { MetadataRoute } from "next";

import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";
import { buildPublicSitemapEntries } from "@/lib/public-site/sitemap";

export default function sitemap(): MetadataRoute.Sitemap {
  return buildPublicSitemapEntries(resolvePublicSiteBaseUrl());
}
