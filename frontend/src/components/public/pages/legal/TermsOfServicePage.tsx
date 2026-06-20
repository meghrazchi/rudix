import { LegalPageLayout } from "./LegalPageLayout";

export function TermsOfServicePage() {
  return (
    <LegalPageLayout
      title="Terms of Service"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. Acceptance",
          body: (
            <p>
              By accessing or using the Rudix platform (&ldquo;Service&rdquo;),
              you agree to be bound by these Terms of Service
              (&ldquo;Terms&rdquo;). If you are using the Service on behalf of
              an organization, you represent that you have authority to bind
              that organization to these Terms. If you do not agree, do not use
              the Service. [LEGAL REVIEW REQUIRED]
            </p>
          ),
        },
        {
          heading: "2. Eligibility",
          body: (
            <p>
              You must be at least 18 years old and authorized to enter into
              contracts in your jurisdiction to use the Service. The Service is
              intended for business use; it is not directed at consumers or
              minors.
            </p>
          ),
        },
        {
          heading: "3. Account Registration",
          body: (
            <p>
              You are responsible for maintaining the security of your account
              credentials. You must not share credentials or allow unauthorized
              access to your account. You agree to notify us immediately of any
              unauthorized use. We reserve the right to suspend accounts that
              exhibit signs of compromise.
            </p>
          ),
        },
        {
          heading: "4. Permitted Use",
          body: (
            <p>
              You may use the Service to upload, index, and query documents
              within your organization&rsquo;s account, subject to these Terms
              and your subscription plan. You may integrate with the Service
              through our API using authorized API keys.
            </p>
          ),
        },
        {
          heading: "5. Restrictions",
          body: (
            <>
              <p>You agree not to:</p>
              <ul className="ml-4 list-disc space-y-1">
                <li>
                  upload content that infringes third-party intellectual
                  property rights or violates applicable law;
                </li>
                <li>
                  attempt to reverse-engineer, decompile, or extract model
                  weights or pipeline logic;
                </li>
                <li>
                  use the Service to generate content intended to deceive,
                  manipulate, or harm individuals;
                </li>
                <li>
                  circumvent rate limits, authentication controls, or
                  organization isolation boundaries;
                </li>
                <li>
                  resell or sublicense access to the Service without written
                  authorization.
                </li>
              </ul>
              <p>
                See our{" "}
                <a href="/legal/acceptable-use" className="underline">
                  Acceptable Use Policy
                </a>{" "}
                for the complete list of prohibited activities.
              </p>
            </>
          ),
        },
        {
          heading: "6. Your Content",
          body: (
            <p>
              You retain ownership of documents and data you upload. By
              uploading content, you grant Rudix a limited license to process
              that content for the purpose of delivering the Service to your
              organization. We do not claim ownership of your documents and will
              not use them to train AI models without your explicit written
              consent.
            </p>
          ),
        },
        {
          heading: "7. Service Availability",
          body: (
            <p>
              We aim to provide a reliable service but do not guarantee
              uninterrupted availability. The Service is provided &ldquo;as
              is&rdquo; for the current release. Planned maintenance is
              communicated in advance via the status page at{" "}
              <a href="/status" className="underline">
                /status
              </a>
              . [LEGAL REVIEW REQUIRED: add SLA terms when applicable.]
            </p>
          ),
        },
        {
          heading: "8. Payments and Subscriptions",
          body: (
            <p>
              Subscription fees are billed in advance on the applicable billing
              cycle. Fees are non-refundable except as required by law or as
              expressly stated in a separate order form. [LEGAL REVIEW REQUIRED:
              complete billing terms before launch.]
            </p>
          ),
        },
        {
          heading: "9. Termination",
          body: (
            <p>
              Either party may terminate these Terms at any time with written
              notice. We may suspend or terminate your access immediately for
              breach of these Terms or the Acceptable Use Policy. Upon
              termination, your data is scheduled for deletion per our retention
              policy. You may request an export before termination.
            </p>
          ),
        },
        {
          heading: "10. Disclaimer of Warranties",
          body: (
            <p>
              The Service is provided without warranty of any kind, express or
              implied. AI-generated answers may be incomplete or incorrect.
              Rudix is not responsible for decisions made based on AI-generated
              content. [LEGAL REVIEW REQUIRED]
            </p>
          ),
        },
        {
          heading: "11. Limitation of Liability",
          body: (
            <p>
              To the maximum extent permitted by law, Rudix&rsquo;s aggregate
              liability for claims arising under these Terms shall not exceed
              the amount paid by you in the twelve months preceding the claim.
              In no event shall we be liable for indirect, incidental, or
              consequential damages. [LEGAL REVIEW REQUIRED]
            </p>
          ),
        },
        {
          heading: "12. Governing Law",
          body: (
            <p>
              These Terms are governed by the laws of [Jurisdiction]. Disputes
              shall be resolved by binding arbitration in [Venue], except that
              either party may seek injunctive relief in any court of competent
              jurisdiction. [LEGAL REVIEW REQUIRED: insert governing law and
              venue.]
            </p>
          ),
        },
        {
          heading: "13. Changes to These Terms",
          body: (
            <p>
              We may update these Terms with 30 days&rsquo; notice for material
              changes. Continued use after the effective date constitutes
              acceptance. We will notify organization administrators by email
              for material changes.
            </p>
          ),
        },
        {
          heading: "14. Contact",
          body: (
            <p>
              For legal inquiries, contact us at{" "}
              <a href="mailto:legal@rudix.ai" className="underline">
                legal@rudix.ai
              </a>
              . [LEGAL REVIEW REQUIRED: verify contact address.]
            </p>
          ),
        },
      ]}
    />
  );
}
