import { LegalPageLayout } from "./LegalPageLayout";

export function SecurityDisclosurePage() {
  return (
    <LegalPageLayout
      title="Security Disclosure Policy"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. Our Commitment",
          body: (
            <p>
              Rudix takes security seriously. We welcome responsible disclosure
              of potential vulnerabilities in the Rudix platform, its APIs, and
              supporting infrastructure. This policy outlines how to report a
              vulnerability and what you can expect from us.
            </p>
          ),
        },
        {
          heading: "2. How to Report",
          body: (
            <>
              <p>
                Please send security reports to{" "}
                <a href="mailto:security@rudix.ai" className="underline">
                  security@rudix.ai
                </a>
                . [LEGAL REVIEW REQUIRED: verify contact address and add PGP key
                if applicable.]
              </p>
              <p>Your report should include:</p>
              <ul className="ml-4 list-disc space-y-1">
                <li>a description of the vulnerability and its potential impact;</li>
                <li>
                  steps to reproduce or a proof-of-concept (no destructive
                  payloads);
                </li>
                <li>affected components, endpoints, or versions;</li>
                <li>your contact information for follow-up.</li>
              </ul>
            </>
          ),
        },
        {
          heading: "3. In-Scope",
          body: (
            <>
              <p>
                The following are in scope for responsible disclosure:
              </p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  Rudix web application (app.rudix.ai or your self-hosted
                  instance);
                </li>
                <li>Rudix REST API endpoints;</li>
                <li>
                  authentication and session management (SSO/SAML, API keys,
                  service accounts);
                </li>
                <li>
                  organization and data isolation vulnerabilities (cross-tenant
                  access);
                </li>
                <li>
                  document upload and processing pipeline (file injection, path
                  traversal, SSRF).
                </li>
              </ul>
            </>
          ),
        },
        {
          heading: "4. Out of Scope",
          body: (
            <>
              <p>The following are out of scope:</p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  attacks against third-party services that Rudix depends on
                  (report those to the respective provider);
                </li>
                <li>
                  denial-of-service attacks or rate-limit bypass that require
                  significant traffic volume;
                </li>
                <li>
                  social engineering of Rudix staff or phishing attacks against
                  Rudix employees;
                </li>
                <li>
                  physical attacks against Rudix infrastructure;
                </li>
                <li>
                  issues in third-party libraries that do not affect Rudix
                  users&rsquo; data.
                </li>
              </ul>
            </>
          ),
        },
        {
          heading: "5. Our Response",
          body: (
            <p>
              We will acknowledge receipt of your report within 2 business days.
              We aim to provide an initial assessment within 5 business days and
              a remediation timeline within 10 business days. We will keep you
              informed of progress. [LEGAL REVIEW REQUIRED: confirm response
              timelines.]
            </p>
          ),
        },
        {
          heading: "6. Responsible Disclosure Guidelines",
          body: (
            <>
              <p>When investigating a vulnerability, please:</p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  use only accounts and data that you own or have explicit
                  permission to test;
                </li>
                <li>
                  avoid accessing, modifying, or deleting other users&rsquo; data;
                </li>
                <li>
                  not exploit the vulnerability beyond what is necessary to
                  demonstrate its existence;
                </li>
                <li>
                  not disclose the vulnerability publicly before we have had a
                  reasonable opportunity to remediate (coordinated disclosure).
                </li>
              </ul>
              <p>
                Researchers who follow these guidelines and disclose in good
                faith will not face legal action from Rudix for their research
                activities. [LEGAL REVIEW REQUIRED]
              </p>
            </>
          ),
        },
        {
          heading: "7. Recognition",
          body: (
            <p>
              We maintain a security acknowledgment page for researchers who
              responsibly disclose valid vulnerabilities. If you would like to be
              credited, include your preferred name or handle in your report.
              [LEGAL REVIEW REQUIRED: confirm recognition program details.]
            </p>
          ),
        },
      ]}
    />
  );
}
