import { SOLUTION_AUDIENCES } from "@/lib/public-site/solutions";

export type EnterpriseUseCaseCard = {
  id: string;
  title: string;
  description: string;
  icon:
    | "knowledge"
    | "hr"
    | "support"
    | "legal"
    | "compliance"
    | "operations"
    | "sales"
    | "procurement"
    | "research"
    | "portal";
  href?: string;
};

export const enterpriseUseCaseCards: EnterpriseUseCaseCard[] = [
  {
    id: "knowledge",
    title: "Internal Knowledge",
    description:
      "Centralize wikis, handbooks, and team documentation for instant employee onboarding.",
    icon: "knowledge",
  },
  {
    id: "hr",
    title: "HR",
    description:
      "Automate policy queries and benefit clarifications with high-precision retrieval.",
    icon: "hr",
    href: SOLUTION_AUDIENCES[0].routePath,
  },
  {
    id: "support",
    title: "Support",
    description:
      "Empower agents with real-time access to technical manuals and resolution histories.",
    icon: "support",
    href: SOLUTION_AUDIENCES[1].routePath,
  },
  {
    id: "legal",
    title: "Legal",
    description:
      "Rapidly extract clauses and analyze contract variances across massive repositories.",
    icon: "legal",
    href: SOLUTION_AUDIENCES[2].routePath,
  },
  {
    id: "compliance",
    title: "Compliance",
    description:
      "Audit regulatory filings and ensure adherence to international standards instantly.",
    icon: "compliance",
    href: SOLUTION_AUDIENCES[3].routePath,
  },
  {
    id: "operations",
    title: "Operations",
    description:
      "Monitor supply chain documentation and operational SOPs with semantic search.",
    icon: "operations",
    href: SOLUTION_AUDIENCES[4].routePath,
  },
  {
    id: "sales",
    title: "Sales",
    description:
      "Arm account executives with competitive intel and case studies during live calls.",
    icon: "sales",
  },
  {
    id: "procurement",
    title: "Procurement",
    description:
      "Streamline vendor evaluations and RFP response extraction through RAG pipelines.",
    icon: "procurement",
  },
  {
    id: "research",
    title: "Research",
    description:
      "Synthesize complex whitepapers and lab data into actionable R&D insights.",
    icon: "research",
    href: SOLUTION_AUDIENCES[5].routePath,
  },
  {
    id: "portal",
    title: "Client Portal",
    description:
      "Provide customers with direct, AI-powered access to their project documentation.",
    icon: "portal",
  },
];

export function AudienceIcon({
  icon,
}: {
  icon: EnterpriseUseCaseCard["icon"];
}) {
  if (icon === "knowledge") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M5 6.5a2 2 0 0 1 2-2h10v15H7a2 2 0 0 1-2-2v-11Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M9 8h6M9 11h6M9 14h4"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "hr") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <circle
          cx="12"
          cy="8"
          r="3.5"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M5.5 19.5c1.4-2.8 4-4.2 6.5-4.2 2.5 0 5.1 1.4 6.5 4.2"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "support") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M7 11.5a5 5 0 0 1 10 0v2.5a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-2.5Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M9 16v1a3 3 0 0 0 6 0v-1"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "legal") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M12 5v14M6 9h12M8 9l-2.5 4.5h5L8 9Zm8 0-2.5 4.5h5L16 9Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "compliance") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M12 4.5 6.5 7v4.8c0 3.5 2 6.7 5.5 8.2 3.5-1.5 5.5-4.7 5.5-8.2V7L12 4.5Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="m9.5 12 1.8 1.8 3.2-3.4"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "operations") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path d="M12 6v12M6 12h12" stroke="currentColor" strokeWidth="1.8" />
        <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  if (icon === "sales") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M6 17.5 10 13.5l3 3L18 11M18 11h-4M18 11v4"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "procurement") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M5 8h14l-1.2 8.2a2 2 0 0 1-2 1.8H8.2a2 2 0 0 1-2-1.8L5 8ZM9 8V6a3 3 0 0 1 6 0v2"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "research") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-7 w-7"
        fill="none"
      >
        <path
          d="M10.5 5.5 8.3 9.2l2.2 3.8h4.3L17 9.2l-2.2-3.7h-4.3ZM8.2 9.2H5.5M18.5 9.2h-2.7M12.6 13v3"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-7 w-7" fill="none">
      <path
        d="M12 5.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13ZM8.8 12h6.4M12 8.8v6.4"
        stroke="currentColor"
        strokeWidth="1.8"
      />
    </svg>
  );
}
