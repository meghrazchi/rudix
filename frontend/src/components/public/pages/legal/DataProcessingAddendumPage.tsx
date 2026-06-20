import { LegalPageLayout } from "./LegalPageLayout";

export function DataProcessingAddendumPage() {
  return (
    <LegalPageLayout
      title="Data Processing Addendum"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. Scope and Purpose",
          body: (
            <p>
              This Data Processing Addendum (&ldquo;DPA&rdquo;) supplements the
              Rudix Terms of Service and applies when Rudix processes personal
              data on behalf of a customer in the context of providing the
              Service. This DPA is intended to satisfy the requirements of the
              GDPR (Regulation (EU) 2016/679) and equivalent data protection
              laws where applicable. [LEGAL REVIEW REQUIRED: adapt to applicable
              jurisdictions.]
            </p>
          ),
        },
        {
          heading: "2. Definitions",
          body: (
            <>
              <p>
                <strong>Controller</strong> means the customer organization that
                determines the purposes and means of processing personal data.
              </p>
              <p>
                <strong>Processor</strong> means Rudix AI, acting on documented
                instructions from the Controller.
              </p>
              <p>
                <strong>Personal data</strong> has the meaning given in the GDPR
                or equivalent applicable law.
              </p>
              <p>
                <strong>Sub-processor</strong> means a third party engaged by
                Rudix to carry out processing activities on behalf of the
                Controller. See our{" "}
                <a href="/legal/subprocessors" className="underline">
                  Subprocessors page
                </a>{" "}
                for the current list.
              </p>
            </>
          ),
        },
        {
          heading: "3. Processing Details",
          body: (
            <>
              <p>
                <strong>Subject-matter.</strong> Processing of documents and
                queries uploaded by the Controller&rsquo;s users for the purpose
                of knowledge retrieval, question answering, and document
                management.
              </p>
              <p>
                <strong>Duration.</strong> For the term of the Service agreement
                plus any statutory retention obligations.
              </p>
              <p>
                <strong>Nature and purpose.</strong> Storage, indexing
                (chunking, embedding, OCR), retrieval, AI-assisted answer
                generation, audit logging.
              </p>
              <p>
                <strong>Data subjects.</strong> Employees, contractors, and
                agents of the Controller whose personal data may appear in
                uploaded documents or queries.
              </p>
            </>
          ),
        },
        {
          heading: "4. Processor Obligations",
          body: (
            <>
              <p>Rudix agrees to:</p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  process personal data only on documented instructions from the
                  Controller;
                </li>
                <li>
                  ensure that personnel authorized to process personal data are
                  bound by confidentiality;
                </li>
                <li>
                  implement appropriate technical and organizational security
                  measures as described in the{" "}
                  <a href="/security" className="underline">
                    Security &amp; Trust page
                  </a>
                  ;
                </li>
                <li>
                  not engage sub-processors without prior authorization, except
                  as listed on the Subprocessors page;
                </li>
                <li>
                  assist the Controller in responding to data subject rights
                  requests;
                </li>
                <li>
                  notify the Controller of a personal data breach without undue
                  delay.
                </li>
              </ul>
            </>
          ),
        },
        {
          heading: "5. Sub-processors",
          body: (
            <p>
              Rudix uses the sub-processors listed at{" "}
              <a href="/legal/subprocessors" className="underline">
                /legal/subprocessors
              </a>
              . We will provide notice of changes to the sub-processor list to
              allow the Controller to object. [LEGAL REVIEW REQUIRED: define
              objection period and process.]
            </p>
          ),
        },
        {
          heading: "6. International Data Transfers",
          body: (
            <p>
              If personal data is transferred outside the European Economic Area
              (EEA), we rely on Standard Contractual Clauses (SCCs) or other
              applicable transfer mechanisms. [LEGAL REVIEW REQUIRED: attach
              SCCs or specify transfer mechanism for each sub-processor.]
            </p>
          ),
        },
        {
          heading: "7. Data Subject Rights",
          body: (
            <p>
              The Controller is responsible for receiving and responding to data
              subject rights requests. Rudix will, upon request, assist the
              Controller by providing functionality to export or delete personal
              data through the Admin Console.
            </p>
          ),
        },
        {
          heading: "8. Security Incident Notification",
          body: (
            <p>
              Rudix will notify the Controller of a confirmed personal data
              breach within 72 hours of becoming aware of it, to the extent
              possible. Notifications will be sent to the primary contact
              registered for the organization. [LEGAL REVIEW REQUIRED: verify
              notification timeline meets GDPR Article 33.]
            </p>
          ),
        },
        {
          heading: "9. Deletion on Termination",
          body: (
            <p>
              Upon termination of the Service agreement, Rudix will delete all
              personal data within [30 days] unless statutory obligations
              require longer retention. The Controller may request a data export
              before deletion. [LEGAL REVIEW REQUIRED: confirm deletion window.]
            </p>
          ),
        },
        {
          heading: "10. Contact for DPA Inquiries",
          body: (
            <p>
              To execute a signed DPA or for DPA-related questions, contact us
              at{" "}
              <a href="mailto:legal@rudix.ai" className="underline">
                legal@rudix.ai
              </a>
              . [LEGAL REVIEW REQUIRED]
            </p>
          ),
        },
      ]}
    />
  );
}
