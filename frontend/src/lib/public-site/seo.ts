import type { Metadata } from "next";

import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";

type BuildPublicMetadataOptions = {
  title: string;
  description: string;
  path: string;
  imagePath?: string;
  noIndex?: boolean;
};

const DEFAULT_OG_IMAGE = "/images/pipeline-rag-sample.png";

export const PUBLIC_SITE_METADATA_DEFAULTS = {
  siteName: "Rudix",
  defaultTitle: "Rudix",
  defaultDescription:
    "Rudix is enterprise-grade RAG infrastructure with secure ingestion, grounded answers, and operational observability.",
};

function ensurePath(path: string): string {
  if (!path) {
    return "/";
  }
  return path.startsWith("/") ? path : `/${path}`;
}

function toAbsoluteUrl(path: string): string {
  const base = resolvePublicSiteBaseUrl();
  return new URL(ensurePath(path), base).toString();
}

export function buildPublicMetadata({
  title,
  description,
  path,
  imagePath = DEFAULT_OG_IMAGE,
  noIndex = false,
}: BuildPublicMetadataOptions): Metadata {
  const canonicalPath = ensurePath(path);
  const canonicalUrl = toAbsoluteUrl(canonicalPath);
  const imageUrl = toAbsoluteUrl(imagePath);

  return {
    title,
    description,
    alternates: {
      canonical: canonicalPath,
    },
    openGraph: {
      type: "website",
      siteName: PUBLIC_SITE_METADATA_DEFAULTS.siteName,
      title,
      description,
      url: canonicalUrl,
      images: [
        {
          url: imageUrl,
          alt: `${title} preview`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [imageUrl],
    },
    robots: {
      index: !noIndex,
      follow: !noIndex,
    },
  };
}
