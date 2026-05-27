export type PlanId = "starter" | "team" | "enterprise";

export type PricingPlan = {
  id: PlanId;
  title: string;
  badge: string;
  summary: string;
  priceLabel: string;
  billingHint: string;
  highlights: string[];
  ctaLabel: string;
};

export const pricingPlans: PricingPlan[] = [
  {
    id: "starter",
    title: "Starter",
    badge: "For focused pilots",
    summary:
      "Launch a secure proof of value for one team with core document Q&A workflows.",
    priceLabel: "Contact us",
    billingHint: "Commercial packaging is finalized during solution review.",
    highlights: [
      "Core document ingestion and citation-backed chat",
      "Starter document and indexing quotas",
      "Baseline usage and quality visibility",
      "Email support and onboarding guidance",
    ],
    ctaLabel: "Start Trial",
  },
  {
    id: "team",
    title: "Team",
    badge: "Most selected for rollout",
    summary:
      "Scale across departments with stronger governance, evaluations, and operational controls.",
    priceLabel: "Contact us",
    billingHint: "Packaging is tailored to usage shape and team requirements.",
    highlights: [
      "Expanded document, storage, and indexing allowances",
      "Evaluation runs and quality tracking workflows",
      "Audit-log visibility and role-aware collaboration",
      "Priority support and architecture advisory",
    ],
    ctaLabel: "Request Demo",
  },
  {
    id: "enterprise",
    title: "Enterprise",
    badge: "For advanced governance needs",
    summary:
      "Align private deployment, security review, and governance requirements for regulated or high-scale environments.",
    priceLabel: "Contact us",
    billingHint:
      "Final terms depend on deployment, controls, and support model.",
    highlights: [
      "Private deployment and environment control options",
      "Advanced governance policies and approval flows",
      "Custom onboarding, success planning, and support",
      "Security review workflow with solution architects",
    ],
    ctaLabel: "Contact Sales",
  },
];

export const usageLimitNotes = [
  {
    title: "Documents and indexing jobs",
    detail:
      "Limits can be tuned by tier for ingestion throughput, queued jobs, and index freshness operations.",
  },
  {
    title: "Questions, tokens, and evaluations",
    detail:
      "Usage controls include chat/question volume, token budgets, and evaluation run allocation.",
  },
  {
    title: "Storage and organizations",
    detail:
      "Tiers can map to storage envelopes, team-member allowances, and organization-level governance needs.",
  },
];

export type ComparisonRow = {
  capability: string;
  starter: string;
  team: string;
  enterprise: string;
};

export const comparisonRows: ComparisonRow[] = [
  {
    capability: "Document capacity",
    starter: "Starter limits",
    team: "Expanded limits",
    enterprise: "Custom program",
  },
  {
    capability: "Storage and indexing",
    starter: "Core indexing workflows",
    team: "Higher indexing throughput",
    enterprise: "Large-scale optimization",
  },
  {
    capability: "Team members and access",
    starter: "Small-team setup",
    team: "Cross-team collaboration",
    enterprise: "Enterprise role model",
  },
  {
    capability: "Evaluation runs",
    starter: "Limited runs",
    team: "Production validation cadence",
    enterprise: "Custom quality program",
  },
  {
    capability: "Audit logs and governance",
    starter: "Basic visibility",
    team: "Expanded governance controls",
    enterprise: "Advanced policy controls",
  },
  {
    capability: "Deployment options",
    starter: "Standard deployment",
    team: "Standard + advisory",
    enterprise: "Private deployment options",
  },
  {
    capability: "Support level",
    starter: "Email support",
    team: "Priority support",
    enterprise: "Dedicated success plan",
  },
];

export const pricingFaqs = [
  {
    question: "Can we start with a trial before committing to a plan?",
    answer:
      "Yes. Teams can begin with a trial workflow and then move to the tier that best fits rollout scope and governance needs.",
  },
  {
    question: "How do upgrades work when our usage grows?",
    answer:
      "Rudix supports staged expansion so you can increase usage, controls, and support without rebuilding your document workflows.",
  },
  {
    question: "Can we request a security review during pricing discussions?",
    answer:
      "Yes. Security-review discussions can be included during plan selection, especially for private deployment or regulated requirements.",
  },
  {
    question: "Do you support self-hosted or private deployment models?",
    answer:
      "Private deployment options are available through enterprise packaging based on infrastructure and governance requirements.",
  },
  {
    question: "Who should we contact for billing and commercial questions?",
    answer:
      "Use the Contact Sales path on this page and the Rudix team will route you to the right commercial contact.",
  },
];
