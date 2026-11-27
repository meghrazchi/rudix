import { LegalPageLayout } from "./LegalPageLayout";

type SubprocessorEntry = {
  name: string;
  purpose: string;
  location: string;
  link?: string;
};

const SUBPROCESSORS: SubprocessorEntry[] = [
  {
    name: "OpenAI",
    purpose:
      "AI language model inference (chat answers, query rewriting, entity extraction)",
    location: "United States",
    link: "https://openai.com/policies/privacy-policy",
  },
  {
    name: "Anthropic",
    purpose: "AI language model inference (optional provider)",
    location: "United States",
    link: "https://www.anthropic.com/privacy",
  },
  {
    name: "Qdrant Cloud (self-hosted option available)",
    purpose: "Vector storage for document embeddings",
    location: "Configurable — defaults to self-hosted",
  },
  {
    name: "MinIO (self-hosted)",
    purpose: "Object storage for raw document files",
    location: "Configured by the deploying organization",
  },
  {
    name: "PostgreSQL (self-hosted)",
    purpose: "Relational database for metadata, audit logs, and user accounts",
    location: "Configured by the deploying organization",
  },
  {
    name: "Neo4j (Enterprise Graph, optional)",
    purpose: "Graph database for entity and relationship storage",
    location: "Configured by the deploying organization",
  },
  {
    name: "Resend / Postmark (optional)",
    purpose: "Transactional email delivery (invitations, notifications)",
    location: "United States",
  },
  {
    name: "Langfuse (optional, self-hosted)",
    purpose: "LLM observability and trace logging",
    location: "Configured by the deploying organization",
  },
];

export function SubprocessorsPage() {
  return (
    <LegalPageLayout
      title="Subprocessors"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "Overview",
          body: (
            <p>
              Rudix engages the following sub-processors to deliver the Service.
              &ldquo;Self-hosted&rdquo; entries are components deployed within
              the customer&rsquo;s own infrastructure and are not operated by
              Rudix. Cloud-hosted AI providers receive document chunks as part
              of inference requests. We will update this list when
              sub-processors are added or removed and notify affected
              organization administrators. [LEGAL REVIEW REQUIRED: confirm list
              accuracy before publication.]
            </p>
          ),
        },
        {
          heading: "Current Subprocessors",
          body: (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-site-border border-b">
                    <th className="text-site-ink pe-4 pb-2 font-semibold">
                      Subprocessor
                    </th>
                    <th className="text-site-ink pe-4 pb-2 font-semibold">
                      Purpose
                    </th>
                    <th className="text-site-ink pb-2 font-semibold">
                      Location
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-site-border divide-y">
                  {SUBPROCESSORS.map((sp) => (
                    <tr key={sp.name}>
                      <td className="text-site-ink py-2 pe-4 align-top font-medium">
                        {sp.link ? (
                          <a
                            href={sp.link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline"
                          >
                            {sp.name}
                          </a>
                        ) : (
                          sp.name
                        )}
                      </td>
                      <td className="text-site-ink-muted py-2 pe-4 align-top">
                        {sp.purpose}
                      </td>
                      <td className="text-site-ink-muted py-2 align-top">
                        {sp.location}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ),
        },
        {
          heading: "Requesting Notification of Changes",
          body: (
            <p>
              If you have executed a DPA with Rudix and wish to receive advance
              notice of sub-processor changes, contact us at{" "}
              <a href="mailto:legal@rudix.ai" className="underline">
                legal@rudix.ai
              </a>
              . [LEGAL REVIEW REQUIRED: define the notification period.]
            </p>
          ),
        },
      ]}
    />
  );
}
