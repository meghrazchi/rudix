import type { Metadata } from "next";

import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";
import { getHtmlLang } from "@/lib/i18n-format";
import {
  DEFAULT_LOCALE,
  isValidLocale,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from "@/i18n/routing";
import enMessages from "@/i18n/messages/en.json";
import deMessages from "@/i18n/messages/de.json";
import esMessages from "@/i18n/messages/es.json";
import frMessages from "@/i18n/messages/fr.json";
import faMessages from "@/i18n/messages/fa.json";
import arMessages from "@/i18n/messages/ar.json";

type BuildPublicMetadataOptions = {
  locale: SupportedLocale;
  title: string;
  description: string;
  path: string;
  imagePath?: string;
  noIndex?: boolean;
};

export type PublicSeoKey =
  | "home"
  | "product"
  | "pricing"
  | "security"
  | "contact"
  | "solutions"
  | "hr"
  | "legal"
  | "compliance"
  | "sales"
  | "support"
  | "research"
  | "operations"
  | "procurement"
  | "internalKnowledge"
  | "clientPortal"
  | "changelog"
  | "status"
  | "privacy"
  | "terms"
  | "cookies"
  | "dpa"
  | "subprocessors"
  | "acceptableUse"
  | "securityDisclosure";

const DEFAULT_OG_IMAGE = "/images/pipeline-rag-sample.png";

const PUBLIC_SEO_COPY: Record<
  SupportedLocale,
  Record<PublicSeoKey, { title: string; description: string }>
> = {
  en: enMessages.public.seo,
  de: deMessages.public.seo,
  es: esMessages.public.seo,
  fr: frMessages.public.seo,
  ar: arMessages.public.seo,
  fa: faMessages.public.seo,
};

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

export function buildLocalizedPublicPath(
  locale: SupportedLocale,
  path: string,
): string {
  const normalizedPath = ensurePath(path);

  if (normalizedPath === "/") {
    return `/${locale}`;
  }

  return `/${locale}${normalizedPath}`;
}

function toAbsoluteUrl(path: string): string {
  const base = resolvePublicSiteBaseUrl();
  return new URL(ensurePath(path), base).toString();
}

function toLocalizedAbsoluteUrl(locale: SupportedLocale, path: string): string {
  return toAbsoluteUrl(buildLocalizedPublicPath(locale, path));
}

function getOpenGraphLocale(locale: SupportedLocale): string {
  const localeMap: Record<SupportedLocale, string> = {
    en: "en_US",
    de: "de_DE",
    es: "es_ES",
    fr: "fr_FR",
    ar: "ar_AR",
    fa: "fa_IR",
  };

  return localeMap[locale];
}

export function buildPublicMetadata({
  locale,
  title,
  description,
  path,
  imagePath = DEFAULT_OG_IMAGE,
  noIndex = false,
}: BuildPublicMetadataOptions): Metadata {
  const resolvedLocale = isValidLocale(locale) ? locale : DEFAULT_LOCALE;
  const canonicalUrl = toLocalizedAbsoluteUrl(resolvedLocale, path);
  const imageUrl = toAbsoluteUrl(imagePath);
  const alternateLocales = SUPPORTED_LOCALES.filter(
    (supportedLocale) => supportedLocale !== resolvedLocale,
  );
  const alternateLanguageUrls: Record<string, string> = {};

  for (const supportedLocale of SUPPORTED_LOCALES) {
    alternateLanguageUrls[getHtmlLang(supportedLocale)] =
      toLocalizedAbsoluteUrl(supportedLocale, path);
  }
  alternateLanguageUrls["x-default"] = toLocalizedAbsoluteUrl(
    DEFAULT_LOCALE,
    path,
  );

  return {
    title,
    description,
    alternates: {
      canonical: canonicalUrl,
      languages: alternateLanguageUrls,
    },
    openGraph: {
      type: "website",
      siteName: PUBLIC_SITE_METADATA_DEFAULTS.siteName,
      locale: getOpenGraphLocale(resolvedLocale),
      alternateLocale: alternateLocales.map(getOpenGraphLocale),
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

export function buildLocalizedPublicMetadata({
  locale,
  seoKey,
  path,
  imagePath,
  noIndex = false,
}: {
  locale: SupportedLocale;
  seoKey: PublicSeoKey;
  path: string;
  imagePath?: string;
  noIndex?: boolean;
}): Metadata {
  const resolvedLocale = isValidLocale(locale) ? locale : DEFAULT_LOCALE;
  const seoCopy = PUBLIC_SEO_COPY[resolvedLocale][seoKey];

  return buildPublicMetadata({
    locale: resolvedLocale,
    title: seoCopy.title,
    description: seoCopy.description,
    path,
    imagePath,
    noIndex,
  });
}
