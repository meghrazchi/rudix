import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

export const PUBLIC_ROUTE_PATHS = {
  home: "/",
  product: "/product",
  solutions: "/solutions",
  security: "/security",
  pricing: "/pricing",
  changelog: "/changelog",
  contact: "/contact",
  status: "/status",
  privacy: "/legal/privacy",
  terms: "/legal/terms",
  cookies: "/legal/cookies",
  dpa: "/legal/dpa",
  subprocessors: "/legal/subprocessors",
  acceptableUse: "/legal/acceptable-use",
  securityDisclosure: "/legal/security-disclosure",
} as const;

export type PublicRouteKey = keyof typeof PUBLIC_ROUTE_PATHS;

export type PublicSiteLinks = {
  home: string;
  product: string;
  solutions: string;
  security: string;
  pricing: string;
  changelog: string;
  login: string;
  requestDemo: string;
  startTrial: string;
  docs: string;
  contact: string;
  securityContact: string;
  status: string;
  app: string;
  privacy: string;
  terms: string;
  cookies: string;
  dpa: string;
  subprocessors: string;
  acceptableUse: string;
  securityDisclosure: string;
};

export type PublicNavItem = {
  label: string;
  href: string;
};

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function resolveEnv(...keys: string[]): string | null {
  for (const key of keys) {
    const value = trimToNull(process.env[key]);
    if (value) {
      return value;
    }
  }
  return null;
}

export function isExternalHref(href: string): boolean {
  return /^(https?:\/\/|mailto:|tel:)/i.test(href);
}

function normalizeContactHref(value: string): string {
  if (isExternalHref(value)) {
    return value;
  }

  if (value.includes("@")) {
    return `mailto:${value}`;
  }

  return value;
}

export function resolvePublicSiteBaseUrl(): string {
  return (
    resolveEnv("NEXT_PUBLIC_PUBLIC_SITE_URL") ??
    getFrontendRuntimeConfig().appUrl
  );
}

export function resolvePublicSiteLinks(): PublicSiteLinks {
  const product =
    resolveEnv("NEXT_PUBLIC_PUBLIC_PRODUCT_URL") ?? PUBLIC_ROUTE_PATHS.product;
  const solutions =
    resolveEnv("NEXT_PUBLIC_PUBLIC_SOLUTIONS_URL") ??
    PUBLIC_ROUTE_PATHS.solutions;
  const security =
    resolveEnv("NEXT_PUBLIC_PUBLIC_SECURITY_URL") ??
    PUBLIC_ROUTE_PATHS.security;
  const pricing =
    resolveEnv("NEXT_PUBLIC_PUBLIC_PRICING_URL") ?? PUBLIC_ROUTE_PATHS.pricing;
  const changelog =
    resolveEnv("NEXT_PUBLIC_PUBLIC_CHANGELOG_URL") ??
    PUBLIC_ROUTE_PATHS.changelog;
  const login = resolveEnv("NEXT_PUBLIC_PUBLIC_LOGIN_URL") ?? "/login";
  const requestDemo =
    resolveEnv("NEXT_PUBLIC_PUBLIC_DEMO_URL") ?? PUBLIC_ROUTE_PATHS.contact;
  const startTrial = resolveEnv("NEXT_PUBLIC_PUBLIC_TRIAL_URL") ?? "/signup";
  const docs =
    resolveEnv("NEXT_PUBLIC_PUBLIC_DOCS_URL", "NEXT_PUBLIC_HELP_DOCS_URL") ??
    "/documents";
  const contact =
    resolveEnv("NEXT_PUBLIC_PUBLIC_CONTACT_URL", "NEXT_PUBLIC_SUPPORT_URL") ??
    PUBLIC_ROUTE_PATHS.contact;
  const securityContactRaw =
    resolveEnv(
      "NEXT_PUBLIC_PUBLIC_SECURITY_CONTACT_URL",
      "NEXT_PUBLIC_SUPPORT_EMAIL",
    ) ?? contact;
  const status =
    resolveEnv("NEXT_PUBLIC_PUBLIC_STATUS_URL") ?? PUBLIC_ROUTE_PATHS.status;
  const app = resolveEnv("NEXT_PUBLIC_PUBLIC_APP_URL") ?? "/dashboard";

  const privacy =
    resolveEnv("NEXT_PUBLIC_PUBLIC_PRIVACY_URL") ?? PUBLIC_ROUTE_PATHS.privacy;
  const terms =
    resolveEnv("NEXT_PUBLIC_PUBLIC_TERMS_URL") ?? PUBLIC_ROUTE_PATHS.terms;
  const cookies =
    resolveEnv("NEXT_PUBLIC_PUBLIC_COOKIES_URL") ?? PUBLIC_ROUTE_PATHS.cookies;
  const dpa =
    resolveEnv("NEXT_PUBLIC_PUBLIC_DPA_URL") ?? PUBLIC_ROUTE_PATHS.dpa;
  const subprocessors =
    resolveEnv("NEXT_PUBLIC_PUBLIC_SUBPROCESSORS_URL") ??
    PUBLIC_ROUTE_PATHS.subprocessors;
  const acceptableUse =
    resolveEnv("NEXT_PUBLIC_PUBLIC_ACCEPTABLE_USE_URL") ??
    PUBLIC_ROUTE_PATHS.acceptableUse;
  const securityDisclosure =
    resolveEnv("NEXT_PUBLIC_PUBLIC_SECURITY_DISCLOSURE_URL") ??
    PUBLIC_ROUTE_PATHS.securityDisclosure;

  return {
    home: PUBLIC_ROUTE_PATHS.home,
    product,
    solutions,
    security,
    pricing,
    changelog,
    login,
    requestDemo,
    startTrial,
    docs,
    contact,
    securityContact: normalizeContactHref(securityContactRaw),
    status,
    app,
    privacy,
    terms,
    cookies,
    dpa,
    subprocessors,
    acceptableUse,
    securityDisclosure,
  };
}

export function buildPrimaryNavItems(links: PublicSiteLinks): PublicNavItem[] {
  return [
    { label: "Product", href: links.product },
    { label: "Solutions", href: links.solutions },
    { label: "Security", href: links.security },
    { label: "Pricing", href: links.pricing },
  ];
}

export function buildFooterLinkGroups(links: PublicSiteLinks): Array<{
  heading: string;
  items: PublicNavItem[];
}> {
  return [
    {
      heading: "Product",
      items: [
        { label: "Product Overview", href: links.product },
        { label: "Pipeline Explorer", href: links.app },
        { label: "Documentation", href: links.docs },
        { label: "Changelog", href: links.changelog },
      ],
    },
    {
      heading: "Solutions",
      items: [
        { label: "Use Cases", href: links.solutions },
        { label: "Security", href: links.security },
        { label: "Pricing", href: links.pricing },
      ],
    },
    {
      heading: "Company & Support",
      items: [
        { label: "Contact", href: links.contact },
        { label: "Status", href: links.status },
        { label: "Login", href: links.login },
      ],
    },
  ];
}
