export type ContactOption = {
  value: string;
  label: string;
};

export const CONTACT_ROLE_OPTIONS: ContactOption[] = [
  { value: "cto_vp_engineering", label: "CTO / VP Engineering" },
  { value: "solutions_architect", label: "Solutions Architect" },
  { value: "devops_sre", label: "DevOps / SRE" },
  { value: "product_management", label: "Product Management" },
  { value: "security_compliance", label: "Security / Compliance" },
  { value: "other", label: "Other" },
];

export const CONTACT_USE_CASE_OPTIONS: ContactOption[] = [
  { value: "rag_pipeline", label: "RAG pipeline optimization" },
  { value: "compliance", label: "Automated compliance workflows" },
  { value: "extraction", label: "High-volume data extraction" },
  { value: "governance", label: "Governance and audit readiness" },
  { value: "migration", label: "Legacy workflow migration" },
  { value: "other", label: "Other" },
];

export const CONTACT_FIT_HIGHLIGHTS: string[] = [
  "Sub-second latency for retrieval-backed Q&A at scale.",
  "Security and privacy guardrails for sensitive document workflows.",
  "Flexible deployment posture for enterprise governance requirements.",
  "Integration planning aligned with existing delivery operations.",
];

export const CONTACT_CARDS = [
  {
    title: "Sales",
    description:
      "Discuss rollout plans, packaging, and enterprise adoption milestones.",
    actionLabel: "Contact Sales",
  },
  {
    title: "Support",
    description:
      "Get setup guidance, onboarding support, and operational best practices.",
    actionLabel: "Contact Support",
  },
  {
    title: "Security review",
    description:
      "Coordinate security and trust review requests with the Rudix team.",
    actionLabel: "Security Contact",
  },
  {
    title: "Status and docs",
    description:
      "Review platform status and implementation documentation anytime.",
    actionLabel: "Open Resources",
  },
] as const;
