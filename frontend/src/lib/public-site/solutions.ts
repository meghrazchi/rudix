export type SolutionSlug =
  | "hr"
  | "support"
  | "legal"
  | "compliance"
  | "operations"
  | "research"
  | "sales";

export type SolutionFaqItem = {
  question: string;
  answer: string;
};

export type SolutionWorkflowStep = {
  title: string;
  description: string;
};

export type SolutionAudience = {
  slug: SolutionSlug;
  name: string;
  shortLabel: string;
  routePath: string;
  teamLabel: string;
  painPoint: string;
  rudixWorkflow: string;
  exampleQuestions: string[];
  summary: string;
  documentSources?: string[];
  workflowSteps?: SolutionWorkflowStep[];
  workflowTitle?: string;
  workflowDescription?: string;
  riskNote?: string;
  outcomes?: string[];
  relatedSlugs?: SolutionSlug[];
  faqItems?: SolutionFaqItem[];
};

export const SOLUTION_AUDIENCES: SolutionAudience[] = [
  {
    slug: "hr",
    name: "HR Knowledge Assistant",
    shortLabel: "HR",
    routePath: "/solutions/hr",
    teamLabel: "People Operations",
    painPoint:
      "Policies, handbooks, and onboarding content are scattered across folders, making answers slow and inconsistent.",
    rudixWorkflow:
      "Centralize HR documents, scope access by role, and deliver citation-backed policy answers for employees and managers.",
    exampleQuestions: [
      "What is the parental leave policy by region?",
      "Which onboarding documents are required before day one?",
      "What is the current reimbursement policy for remote work?",
      "How many days of sick leave does an employee accrue per month?",
      "Where can I find the benefits enrollment deadline for this year?",
      "What does the policy say about manager approval for overtime?",
      "Is there a formal process for requesting a role change?",
      "What happens if a question is not covered in the current handbook?",
    ],
    summary:
      "Support HR teams with faster, consistent responses grounded in approved internal policy sources.",
    documentSources: [
      "Employee handbook",
      "Benefits enrollment guide",
      "Onboarding packets",
      "Leave and time-off policies",
      "Remote work and expense SOPs",
      "Role transition and promotion guides",
      "Training and certification materials",
      "Disciplinary and performance procedures",
    ],
    workflowTitle: "How HR teams use Rudix",
    workflowDescription:
      "A repeatable process from first upload to consistently answered policy questions.",
    workflowSteps: [
      {
        title: "Upload policies",
        description:
          "Add handbooks, benefits guides, onboarding packets, and SOPs into a governed workspace.",
      },
      {
        title: "Index documents",
        description:
          "Rudix processes and chunks content into searchable context ready for retrieval.",
      },
      {
        title: "Ask questions",
        description:
          "Employees and HR operators ask policy questions in plain language.",
      },
      {
        title: "Review citations",
        description:
          "Every answer includes source citations so teams can trace the exact document and section.",
      },
      {
        title: "Evaluate quality",
        description:
          "Run evaluations against expected answers to monitor retrieval accuracy over time.",
      },
      {
        title: "Update stale content",
        description:
          "Replace outdated policy versions and reindex to keep answers current.",
      },
    ],
    riskNote:
      "Rudix provides grounded answers from uploaded documents — it does not make employment decisions, legal determinations, or compliance rulings. Sensitive employee information should be governed under your organization's data policies. Role-scoped access controls ensure employees only retrieve content appropriate to their access level.",
    outcomes: [
      "Faster policy lookups for employees and HR teams",
      "Fewer repetitive policy questions routed to the HR inbox",
      "Consistent onboarding answers across regions and roles",
      "Clear document-level source of truth for every response",
    ],
    relatedSlugs: ["compliance", "operations"],
    faqItems: [
      {
        question: "Can employees use the HR assistant without HR oversight?",
        answer:
          "Access scope is controlled by your organization. HR teams can restrict which documents are queryable and by whom, so employees only retrieve content appropriate to their role.",
      },
      {
        question: "How is sensitive employee data protected?",
        answer:
          "Rudix does not store document content beyond what is indexed for retrieval. Your data governance policies and role-based access controls govern who can query which documents.",
      },
      {
        question: "What happens when a policy changes?",
        answer:
          "Replace the outdated document version and reindex. Answers automatically draw from the updated content on the next query.",
      },
    ],
  },
  {
    slug: "support",
    name: "Customer Support Resolution Hub",
    shortLabel: "Support",
    routePath: "/solutions/support",
    teamLabel: "Customer Support",
    painPoint:
      "Support reps spend too much time searching across runbooks, product notes, and escalation docs during live tickets.",
    rudixWorkflow:
      "Index support documentation and retrieval paths so teams can respond with evidence-based answers and quicker handoffs.",
    exampleQuestions: [
      "How do we troubleshoot SSO login failures for enterprise tenants?",
      "Which version introduced this known issue and workaround?",
      "What is the escalation path for payment-service outages?",
    ],
    summary:
      "Help support teams reduce resolution time with reliable, source-backed answers across ticket workflows.",
  },
  {
    slug: "legal",
    name: "Legal Review and Obligation Assist",
    shortLabel: "Legal",
    routePath: "/solutions/legal",
    teamLabel: "Legal Teams",
    painPoint:
      "Contract terms and obligations are difficult to track across versions, leading to manual review overhead and missed context.",
    rudixWorkflow:
      "Surface relevant clauses, compare policy language, and provide grounded legal-reference answers with traceable citations.",
    exampleQuestions: [
      "Where are data-retention obligations defined in this agreement?",
      "What termination notice periods differ across contract templates?",
      "Which clauses require customer-side security attestations?",
    ],
    summary:
      "Enable legal teams to move faster on review cycles while preserving citation traceability for every answer.",
  },
  {
    slug: "compliance",
    name: "Compliance Evidence Navigator",
    shortLabel: "Compliance",
    routePath: "/solutions/compliance",
    teamLabel: "Compliance and Risk",
    painPoint:
      "Audit evidence and control narratives are spread across systems, making readiness checks time-consuming and error-prone.",
    rudixWorkflow:
      "Map control documents into searchable context, track evaluation quality, and keep governance visibility for audit workflows.",
    exampleQuestions: [
      "Which controls map to SOC 2 change-management requirements?",
      "What evidence supports incident-response tabletop completion?",
      "Where is the latest policy exception approval documented?",
    ],
    summary:
      "Give compliance teams a faster path from evidence requests to grounded, review-ready responses.",
  },
  {
    slug: "operations",
    name: "Operations Runbook Intelligence",
    shortLabel: "Operations",
    routePath: "/solutions/operations",
    teamLabel: "IT and Operations",
    painPoint:
      "Operational playbooks and troubleshooting guides drift over time, creating inconsistent execution during incidents.",
    rudixWorkflow:
      "Index runbooks and incident docs, validate answer confidence, and monitor retrieval quality to improve operational consistency.",
    exampleQuestions: [
      "What is the approved rollback sequence for deployment failures?",
      "Which alerts require immediate paging during business hours?",
      "What are the post-incident documentation requirements?",
    ],
    summary:
      "Equip operations teams with consistent guidance and faster decision support during critical workflows.",
  },
  {
    slug: "research",
    name: "Research and Strategy Briefing",
    shortLabel: "Research",
    routePath: "/solutions/research",
    teamLabel: "Research and Strategy",
    painPoint:
      "Analysts lose time reconciling long reports and fragmented notes before building briefings or recommendations.",
    rudixWorkflow:
      "Search across research corpora, compare sources, and produce grounded summaries with cited evidence for leadership briefings.",
    exampleQuestions: [
      "What themes appear across the latest market outlook reports?",
      "Which findings contradict last quarter's assumptions?",
      "What evidence supports this strategic recommendation?",
    ],
    summary:
      "Accelerate research synthesis with grounded answers and clearer evidence trails for strategic decisions.",
  },
  {
    slug: "sales",
    name: "Sales Enablement Engine",
    shortLabel: "Sales",
    routePath: "/solutions/sales",
    teamLabel: "Sales and Revenue",
    painPoint:
      "AEs and SEs waste hours searching for battlecards, pricing sheets, and case studies during live deal cycles.",
    rudixWorkflow:
      "Index approved sales collateral and product knowledge so reps get cited, accurate answers during calls and proposal prep.",
    exampleQuestions: [
      "Which case study fits a healthcare prospect looking for SOC2 compliance?",
      "What are our competitive advantages against Enterprise-X?",
      "Can we offer a 15% discount for a 3-year term on the Enterprise tier?",
      "What does the implementation guide say about onboarding timelines?",
      "Which RFP template covers data residency requirements?",
    ],
    summary:
      "Empower sales teams to answer deal questions instantly with cited answers from battlecards, RFP templates, pricing sheets, and product specs.",
    documentSources: [
      "Product specifications",
      "Case studies",
      "RFP and RFI templates",
      "Pricing sheets",
      "Competitive battlecards",
      "Proposal decks",
      "Implementation guides",
      "Customer success playbooks",
    ],
    workflowTitle: "How sales teams use Rudix",
    workflowDescription:
      "From uploaded collateral to cited deal intelligence, without leaving your workflow.",
    workflowSteps: [
      {
        title: "Upload approved collateral",
        description:
          "Add battlecards, pricing sheets, case studies, and RFP templates into a governed workspace.",
      },
      {
        title: "Index documents",
        description:
          "Rudix processes and chunks content for precision retrieval during live deal interactions.",
      },
      {
        title: "Ask deal questions",
        description:
          "AEs and SEs ask competitive, pricing, and product questions in plain language.",
      },
      {
        title: "Verify citations",
        description:
          "Every answer links back to the source document so reps can cite evidence confidently.",
      },
      {
        title: "Evaluate accuracy",
        description:
          "Run evaluations to keep answer quality high as collateral and pricing evolve.",
      },
      {
        title: "Update stale content",
        description:
          "Replace outdated battlecards or pricing versions and reindex to keep answers current.",
      },
    ],
    riskNote:
      "Rudix surfaces answers from approved uploaded documents — it does not generate commercial commitments, finalize pricing, or replace legal review. All deal-specific terms must be validated by the appropriate owner before being communicated to prospects.",
    outcomes: [
      "Faster RFP and proposal response cycles",
      "Consistent competitive positioning across the team",
      "Fewer escalations to product and legal for standard deal questions",
      "Citation-backed answers reps can share with confidence",
    ],
    relatedSlugs: ["legal", "research", "operations"],
  },
];

export const SOLUTION_ROLE_NAV = SOLUTION_AUDIENCES.map((solution) => ({
  label: `${solution.shortLabel} Teams`,
  href: solution.routePath,
}));

export const SOLUTION_OVERVIEW_FLOW_STEPS = [
  {
    title: "Collect",
    description:
      "Bring department documents into one governed workspace instead of scattered repositories.",
  },
  {
    title: "Prepare",
    description:
      "Validate, structure, and index content so teams can search trusted context quickly.",
  },
  {
    title: "Answer",
    description:
      "Provide citation-backed responses for real department workflows, not generic chat output.",
  },
  {
    title: "Improve",
    description:
      "Use evaluations, auditability, and monitoring to raise quality and consistency over time.",
  },
];

export function getSolutionAudienceBySlug(
  solutionSlug: string,
): SolutionAudience | null {
  return (
    SOLUTION_AUDIENCES.find((solution) => solution.slug === solutionSlug) ??
    null
  );
}
