import Link from "next/link";

import { LegalPageLayout } from "./LegalPageLayout";

export function PrivacyPolicyPage() {
  return (
    <LegalPageLayout
      title="Privacy Policy"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. Overview",
          body: (
            <p>
              Rudix AI (&ldquo;Rudix,&rdquo; &ldquo;we,&rdquo; &ldquo;us,&rdquo;
              or &ldquo;our&rdquo;) operates the Rudix enterprise RAG platform.
              This Privacy Policy describes how we collect, use, store, and
              protect information when you use our services. It applies to
              account holders, end users, and administrators within customer
              organizations.
            </p>
          ),
        },
        {
          heading: "2. Information We Collect",
          body: (
            <>
              <p>
                <strong>Account and identity data.</strong> When you register or
                join an organization on Rudix, we collect your name, email
                address, password hash (Argon2id), and optional profile
                information such as a display avatar. Service accounts are also
                identified by a scoped bearer token.
              </p>
              <p>
                <strong>Uploaded documents.</strong> You may upload files (PDF,
                DOCX, and other supported formats) for indexing and retrieval.
                Document content is processed through the ingestion pipeline
                (chunking, OCR, embedding) and stored in organization-scoped
                storage. Raw file bytes are retained in object storage; derived
                vectors are stored in a separate vector index.
              </p>
              <p>
                <strong>Chat and query data.</strong> Questions submitted to the
                chat interface, the resulting AI-generated answers, cited
                sources, and any feedback you provide on answers are associated
                with your session and organization.
              </p>
              <p>
                <strong>Usage and telemetry data.</strong> We collect event
                logs, API request metadata, model usage counts, and latency
                metrics for operational purposes and cost accounting. These
                records are retained in audit logs.
              </p>
              <p>
                <strong>Support and contact data.</strong> Information you
                submit via contact forms or support channels is used solely to
                respond to your inquiry.
              </p>
            </>
          ),
        },
        {
          heading: "3. How We Use Your Information",
          body: (
            <>
              <p>
                <strong>Providing the service.</strong> Uploaded documents are
                processed to build a searchable index. Queries are routed
                through a retrieval pipeline and sent to AI model providers to
                generate grounded answers.
              </p>
              <p>
                <strong>Authentication and access control.</strong> Account
                credentials are used to authenticate users and enforce
                organization-level role permissions.
              </p>
              <p>
                <strong>Operational monitoring.</strong> Usage events, failed
                jobs, and pipeline metrics are used to detect and resolve
                service issues.
              </p>
              <p>
                <strong>Product improvement.</strong> Aggregated, de-identified
                analytics may be used to improve pipeline quality, model
                routing, and retrieval accuracy. Raw document content is not
                used for model training without explicit written agreement.
              </p>
            </>
          ),
        },
        {
          heading: "4. AI Model Providers",
          body: (
            <p>
              Rudix routes queries to third-party AI model providers
              (sub-processors) to generate answers. Relevant document chunks are
              included in prompts sent to these providers. See our{" "}
              <Link href="/legal/subprocessors" className="underline">
                Subprocessors page
              </Link>{" "}
              for the current list of AI providers and their data processing
              locations. You can configure which model provider your
              organization uses from the Admin Console.
            </p>
          ),
        },
        {
          heading: "5. Data Storage and Security",
          body: (
            <>
              <p>
                Document files are stored in an object store (MinIO or
                compatible). Vector embeddings are stored in Qdrant. Metadata
                and audit logs are stored in PostgreSQL. All data at rest is
                encrypted using AES-256. Transport is encrypted via TLS.
              </p>
              <p>
                Organization data is logically isolated: cross-tenant access
                controls are enforced at every storage and API layer.
                Organization administrators can configure additional access
                policies from the Admin Console.
              </p>
            </>
          ),
        },
        {
          heading: "6. Data Retention and Deletion",
          body: (
            <>
              <p>
                Documents remain in the system until you delete them or your
                organization account is closed. Deletion requests enter a
                lifecycle queue; documents transition through
                &ldquo;delete_requested&rdquo; and
                &ldquo;retained_by_policy&rdquo; states before permanent
                removal. Audit log records may be retained beyond document
                deletion to satisfy compliance obligations.
              </p>
              <p>
                If you close your organization account, all associated document
                content, vectors, and user data are scheduled for permanent
                deletion. You may request early deletion via our support
                channel.
              </p>
            </>
          ),
        },
        {
          heading: "7. Your Rights",
          body: (
            <p>
              Depending on your jurisdiction, you may have rights to access,
              correct, export, or delete personal data we hold about you. To
              exercise these rights, contact us at the address below. We will
              respond within the timeframe required by applicable law.
              Organization administrators can also export or delete user data
              from the Admin Console.
            </p>
          ),
        },
        {
          heading: "8. Cookies and Browser Storage",
          body: (
            <p>
              We use session cookies and browser-local storage to maintain
              authentication state and user preferences. See our{" "}
              <Link href="/legal/cookies" className="underline">
                Cookie Policy
              </Link>{" "}
              for details.
            </p>
          ),
        },
        {
          heading: "9. Changes to This Policy",
          body: (
            <p>
              We may update this policy as the product evolves. We will update
              the version number and effective date at the top of this page and,
              for material changes, notify organization administrators by email.
              Continued use of the service after the effective date constitutes
              acceptance of the updated policy.
            </p>
          ),
        },
        {
          heading: "10. Contact",
          body: (
            <p>
              For privacy inquiries, contact us at{" "}
              <a href="mailto:privacy@rudix.ai" className="underline">
                privacy@rudix.ai
              </a>
              . [LEGAL REVIEW REQUIRED: verify contact address before
              publication.]
            </p>
          ),
        },
      ]}
    />
  );
}
