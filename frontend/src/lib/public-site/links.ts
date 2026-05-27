export const PUBLIC_ROUTE_PATHS = {
  home: "/",
  product: "/product",
  solutions: "/solutions",
  security: "/security",
  pricing: "/pricing",
  contact: "/contact",
  status: "/status",
} as const;

export type PublicRouteKey = keyof typeof PUBLIC_ROUTE_PATHS;

export type PublicSiteLinks = {
  home: string;
  product: string;
  solutions: string;
  security: string;
  pricing: string;
  login: string;
  requestDemo: string;
  startTrial: string;
  docs: string;
  contact: string;
  securityContact: string;
  status: string;
  app: string;
};

export type PublicNavItem = {
  label: string;
  href: string;
};

const FALLBACK_SITE_URL = "http://localhost:3000";

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
    resolveEnv("NEXT_PUBLIC_PUBLIC_SITE_URL", "NEXT_PUBLIC_APP_URL") ??
    FALLBACK_SITE_URL
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

  return {
    home: PUBLIC_ROUTE_PATHS.home,
    product,
    solutions,
    security,
    pricing,
    login,
    requestDemo,
    startTrial,
    docs,
    contact,
    securityContact: normalizeContactHref(securityContactRaw),
    status,
    app,
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
