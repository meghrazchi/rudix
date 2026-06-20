export type PublicChangelogCategory = {
  title: "Added" | "Improved" | "Fixed" | "Breaking changes";
  items: string[];
};

export type PublicChangelogLink = {
  label: string;
  href: string;
};

export type PublicChangelogEntry = {
  version: string;
  date: string;
  milestone: string;
  sourceTag: string;
  sourceMilestone: string;
  summary: string;
  categories: PublicChangelogCategory[];
  links: PublicChangelogLink[];
  isCurrent?: boolean;
};

export const PUBLIC_CHANGELOG_ENTRIES: PublicChangelogEntry[] = [
  {
    version: "v0.7.0",
    date: "June 20, 2026",
    milestone: "Product Polish & Legal",
    sourceTag: "v0.7.0",
    sourceMilestone: "Product Polish & Legal",
    summary:
      "Public release notes now track visible product changes, safe links, and a lighter publishing workflow.",
    categories: [
      {
        title: "Added",
        items: [
          "Public /changelog route with current and historical release notes.",
          "Footer and help-menu links so release notes are easy to find.",
          "Structured release note source data with version, milestone, and category fields.",
        ],
      },
      {
        title: "Improved",
        items: [
          "Clearer release note conventions for public-safe summaries.",
          "Simpler update flow for product polish and legal-facing changes.",
        ],
      },
      {
        title: "Fixed",
        items: [
          "Reduced the chance of exposing internal-only details in public updates.",
        ],
      },
    ],
    links: [
      { label: "Review the product overview", href: "/product" },
      { label: "Read the security posture", href: "/security" },
      { label: "Contact the team", href: "/contact" },
    ],
    isCurrent: true,
  },
  {
    version: "v0.6.0",
    date: "May 14, 2026",
    milestone: "Evaluation & Observability",
    sourceTag: "v0.6.0",
    sourceMilestone: "Evaluation & Observability",
    summary:
      "Evaluation reporting and operational visibility were expanded for day-to-day product and release work.",
    categories: [
      {
        title: "Added",
        items: [
          "Expanded evaluation reporting surfaces for quality tracking.",
          "More visible pipeline and observability entry points across the app.",
        ],
      },
      {
        title: "Improved",
        items: [
          "Sharper operational feedback for long-running document workflows.",
          "More consistent navigation between metrics and product pages.",
        ],
      },
      {
        title: "Fixed",
        items: [
          "Tightened copy and state handling around operational summaries.",
        ],
      },
    ],
    links: [
      { label: "Explore evaluations", href: "/evaluations" },
      { label: "Open pipeline explorer", href: "/rag-pipeline" },
    ],
  },
  {
    version: "v0.5.0",
    date: "April 3, 2026",
    milestone: "Security & Onboarding",
    sourceTag: "v0.5.0",
    sourceMilestone: "Security & Onboarding",
    summary:
      "Public entry points, onboarding language, and security messaging were refined for clearer first-time use.",
    categories: [
      {
        title: "Added",
        items: [
          "Clearer onboarding guidance for new users and workspaces.",
          "More direct security and trust messaging for public visitors.",
        ],
      },
      {
        title: "Improved",
        items: [
          "Better top-level route discoverability on the public site.",
          "Safer defaults for public-facing support and policy links.",
        ],
      },
      {
        title: "Fixed",
        items: ["Minor content polish across public navigation and CTAs."],
      },
    ],
    links: [
      { label: "Read the legal solution page", href: "/solutions/legal" },
      { label: "Review the security page", href: "/security" },
    ],
  },
];

export function getPublicChangelogEntries(): PublicChangelogEntry[] {
  return [...PUBLIC_CHANGELOG_ENTRIES];
}
