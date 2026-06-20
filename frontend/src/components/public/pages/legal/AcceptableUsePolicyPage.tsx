import { LegalPageLayout } from "./LegalPageLayout";

export function AcceptableUsePolicyPage() {
  return (
    <LegalPageLayout
      title="Acceptable Use Policy"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. Purpose",
          body: (
            <p>
              This Acceptable Use Policy (&ldquo;AUP&rdquo;) defines permitted
              and prohibited uses of the Rudix platform. It applies to all users,
              including organization administrators, end users, and API
              integrations using service account tokens.
            </p>
          ),
        },
        {
          heading: "2. Permitted Uses",
          body: (
            <>
              <p>You may use the Service to:</p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  upload and index documents that your organization owns or is
                  licensed to process;
                </li>
                <li>
                  query indexed content for legitimate business purposes such as
                  knowledge retrieval, research, and document analysis;
                </li>
                <li>
                  configure connectors to ingest content from authorized
                  external systems (Confluence, Jira, Google Drive);
                </li>
                <li>
                  build internal tools and automations using the Rudix API under
                  an authorized service account.
                </li>
              </ul>
            </>
          ),
        },
        {
          heading: "3. Prohibited Uses",
          body: (
            <>
              <p>
                You must not use the Service in any way that:
              </p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  violates applicable laws or regulations, including data
                  protection laws or export control restrictions;
                </li>
                <li>
                  uploads content you do not have the right to process,
                  including unlicensed copyrighted material or documents subject
                  to a confidentiality agreement you cannot waive;
                </li>
                <li>
                  uploads or processes special categories of personal data
                  (health records, biometric data, etc.) without appropriate
                  legal basis and DPA in place;
                </li>
                <li>
                  attempts to probe, scan, or exploit vulnerabilities in the
                  platform (see our{" "}
                  <a href="/legal/security-disclosure" className="underline">
                    Security Disclosure Policy
                  </a>{" "}
                  for authorized research);
                </li>
                <li>
                  attempts to circumvent organization isolation controls,
                  access another tenant&rsquo;s data, or escalate privileges
                  beyond those granted by your role;
                </li>
                <li>
                  deliberately triggers excessive API requests to degrade
                  service performance (denial of service);
                </li>
                <li>
                  uses AI-generated answers to spread disinformation,
                  impersonate individuals, or produce harmful content;
                </li>
                <li>
                  resells or sublicenses Service access without written
                  authorization from Rudix.
                </li>
              </ul>
            </>
          ),
        },
        {
          heading: "4. Content Standards",
          body: (
            <p>
              Documents uploaded to the platform must not contain malicious
              code, exploit payloads, or content designed to compromise Rudix
              infrastructure. We apply automated security scanning (magic-byte
              validation, DLP checks) to uploads; uploads that fail security
              checks will be quarantined. Organization administrators are
              responsible for reviewing quarantined items.
            </p>
          ),
        },
        {
          heading: "5. Enforcement",
          body: (
            <p>
              We may suspend or terminate Service access for any account that
              violates this AUP, with or without prior notice depending on
              severity. For minor violations we will attempt to notify the
              organization administrator before taking action. We reserve the
              right to report suspected illegal activity to appropriate
              authorities.
            </p>
          ),
        },
        {
          heading: "6. Reporting Abuse",
          body: (
            <p>
              If you become aware of a violation of this AUP, including misuse
              of Rudix infrastructure or harmful use of AI-generated content,
              report it to{" "}
              <a href="mailto:abuse@rudix.ai" className="underline">
                abuse@rudix.ai
              </a>
              . [LEGAL REVIEW REQUIRED: verify contact address.]
            </p>
          ),
        },
        {
          heading: "7. Changes",
          body: (
            <p>
              We may update this AUP to reflect changes in the Service or legal
              requirements. We will notify organization administrators of
              material changes with at least 14 days&rsquo; notice.
            </p>
          ),
        },
      ]}
    />
  );
}
