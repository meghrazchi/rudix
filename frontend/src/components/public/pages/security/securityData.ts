export type SecurityPillarIcon =
  | "privacy"
  | "isolation"
  | "access"
  | "audit"
  | "upload"
  | "encryption"
  | "observability";

export type SecurityPillar = {
  title: string;
  description: string;
  icon: SecurityPillarIcon;
  callout: string;
};

export const securityPillars: SecurityPillar[] = [
  {
    title: "Document privacy",
    description:
      "Documents are handled inside organization-scoped workflows with protected storage and controlled retrieval paths.",
    icon: "privacy",
    callout: "Privacy-first defaults",
  },
  {
    title: "Organization isolation",
    description:
      "Data access stays tenant-aware so teams only retrieve content from the organization they belong to.",
    icon: "isolation",
    callout: "Tenant-scoped access boundaries",
  },
  {
    title: "Access control",
    description:
      "Role-aware permissions are enforced across document actions, retrieval operations, and admin surfaces.",
    icon: "access",
    callout: "Least-privilege role model",
  },
  {
    title: "Audit logs",
    description:
      "Security-relevant actions can be tracked with request context to support operational reviews and investigations.",
    icon: "audit",
    callout: "Traceable activity records",
  },
  {
    title: "Safe uploads",
    description:
      "Uploads are validated before processing to reduce malformed payload risks and protect ingestion quality.",
    icon: "upload",
    callout: "Validation before indexing",
  },
  {
    title: "Encryption posture",
    description:
      "Rudix is designed for encrypted transport and encrypted storage aligned to enterprise deployment controls.",
    icon: "encryption",
    callout: "Encrypted in transit and at rest",
  },
  {
    title: "Operational observability",
    description:
      "Teams can monitor request health and failures with safe telemetry that avoids exposing sensitive document text.",
    icon: "observability",
    callout: "Safe operational visibility",
  },
];

export const documentLifecycleStages: Array<{
  title: string;
  description: string;
}> = [
  {
    title: "Validate",
    description: "Check file type and structure before processing begins.",
  },
  {
    title: "Store",
    description: "Write accepted files to protected object storage.",
  },
  {
    title: "Parse",
    description: "Extract structured text and metadata safely.",
  },
  {
    title: "Chunk",
    description: "Split content into retrieval-friendly segments.",
  },
  {
    title: "Embed",
    description: "Generate vector representations for search.",
  },
  {
    title: "Index",
    description: "Publish scoped vectors to the organization index.",
  },
  {
    title: "Answer with citations",
    description: "Return responses grounded in source references.",
  },
  {
    title: "Delete",
    description: "Honor deletion workflows across storage and indices.",
  },
  {
    title: "Re-index",
    description: "Rebuild index state when content is updated.",
  },
];

export const accessAndGovernanceCards = [
  {
    title: "Authentication and session safety",
    description:
      "Authenticated flows are separated from public pages, with session checks and protected-route boundaries.",
  },
  {
    title: "Role-aware access",
    description:
      "Permissions can be scoped by role and organization context to control document and admin actions.",
  },
  {
    title: "Admin governance",
    description:
      "Administrative controls support policy management, tooling guardrails, and operational review workflows.",
  },
  {
    title: "Public/private route boundaries",
    description:
      "Marketing routes remain public while application workspaces require authenticated access.",
  },
];

export const sampleAuditEvents = [
  {
    timestamp: "2026-05-24 09:14:23",
    actor: "admin_user",
    action: "POLICY_UPDATE",
    resource: "governance/tool-allowlist",
    status: "Success",
  },
  {
    timestamp: "2026-05-24 09:07:42",
    actor: "service_worker",
    action: "DOCUMENT_INDEX",
    resource: "documents/employee-handbook",
    status: "Success",
  },
  {
    timestamp: "2026-05-24 08:59:11",
    actor: "unknown_request",
    action: "ACCESS_ATTEMPT",
    resource: "api/documents",
    status: "Rejected",
  },
];

export const complianceReadinessItems = [
  "Security documentation and control mappings can be shared during enterprise review.",
  "Readiness for SOC 2, GDPR, HIPAA, or ISO workflows depends on your deployment controls and validation process.",
  "Rudix does not claim certifications for your organization unless verified in your environment.",
];

export const retentionAndDeletionItems = [
  "Retention timelines should be defined by your organization policy and legal requirements.",
  "Deletion workflows should cover object storage, searchable indices, and derived artifacts.",
  "Re-index workflows support stale-document refresh and policy updates.",
];

export const securityFaqs = [
  {
    question: "Does Rudix expose raw document text in logs by default?",
    answer:
      "Rudix is designed for safe observability and avoids exposing raw protected document text in default operational logs.",
  },
  {
    question: "Can we keep Rudix in a private deployment model?",
    answer:
      "Yes. Rudix supports deployment patterns where infrastructure and data handling stay inside your controlled environment.",
  },
  {
    question: "How does organization isolation work?",
    answer:
      "Access checks and retrieval filters are organization-scoped so data stays separated across tenants.",
  },
  {
    question: "Can we review security controls before rollout?",
    answer:
      "Yes. Use a security review session to validate architecture, access controls, and data-handling requirements for your use case.",
  },
];
