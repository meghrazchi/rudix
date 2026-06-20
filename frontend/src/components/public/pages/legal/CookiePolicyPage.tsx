import { LegalPageLayout } from "./LegalPageLayout";

export function CookiePolicyPage() {
  return (
    <LegalPageLayout
      title="Cookie Policy"
      version="0.2"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. What Are Cookies",
          body: (
            <p>
              Cookies are small text files stored in your browser when you visit
              a website. We also use the browser&rsquo;s localStorage for
              certain persistent preferences. This policy explains what we
              store, why, and how you can control it.
            </p>
          ),
        },
        {
          heading: "2. Cookie Categories",
          body: (
            <>
              <p>
                We group what we store into four categories. The consent banner
                shown on your first visit lets you accept or decline each
                optional category. You can change your choice at any time by
                clicking &ldquo;Customize&rdquo; in the consent banner, which
                reappears when you clear your browser data.
              </p>
              <p>
                <strong>Necessary (always on).</strong> An HTTP-only, secure
                session cookie stores your authenticated session token. A
                same-site CSRF protection cookie guards form submissions. Both
                are cleared when you sign out or your session expires and cannot
                be disabled.
              </p>
              <p>
                <strong>Functional (optional).</strong> Your selected display
                language (English, German, French, or Spanish) is stored in
                localStorage under the key <code>rudix_lang</code>. Your last
                selected chat scope setting is also stored in localStorage.
                These preferences contain no personal data. If you decline this
                category your language and scope selections will not persist
                across page loads.
              </p>
              <p>
                <strong>Analytics (optional).</strong> When analytics are
                enabled and you have given consent, aggregate usage data is
                collected to help us improve the product. No personal content
                or document text is included. Data is not shared with
                advertising networks.
              </p>
              <p>
                <strong>Marketing.</strong> We do not use marketing or
                advertising cookies. No cross-site tracking pixels or
                advertising network integrations are present.
              </p>
            </>
          ),
        },
        {
          heading: "3. Your Consent Choices",
          body: (
            <>
              <p>
                On your first visit a consent banner appears at the bottom of
                the page. You may:
              </p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Accept all</strong> — enable Functional and Analytics
                  cookies in addition to the required Necessary cookies.
                </li>
                <li>
                  <strong>Reject non-essential</strong> — use only the
                  Necessary cookies required to run the service.
                </li>
                <li>
                  <strong>Customize</strong> — open the preferences panel and
                  toggle each optional category individually.
                </li>
              </ul>
              <p>
                Your preference is stored in your browser&rsquo;s localStorage
                under the key <code>rudix.consent.v1</code> and includes the
                policy version at the time you decided. If we update this policy
                in a way that changes what is collected, the banner will
                re-appear and ask you to review your choices.
              </p>
            </>
          ),
        },
        {
          heading: "4. How to Change or Withdraw Consent",
          body: (
            <>
              <p>
                To change your preferences, clear your browser&rsquo;s
                localStorage (or the <code>rudix.consent.v1</code> key
                specifically). The consent banner will reappear on your next
                visit. You can also delete all browser cookies for this site
                through your browser&rsquo;s privacy settings — deleting the
                session cookie will sign you out of the application.
              </p>
            </>
          ),
        },
        {
          heading: "5. Changes to This Policy",
          body: (
            <p>
              If we introduce new cookies or tracking technologies, we will
              update this policy and increment the version number. Where the
              change affects optional categories, the consent banner will
              re-prompt you. The version number and effective date at the top of
              this page reflect the latest revision.
            </p>
          ),
        },
        {
          heading: "6. Contact",
          body: (
            <p>
              For questions about our use of cookies, contact us at{" "}
              <a href="mailto:privacy@rudix.ai" className="underline">
                privacy@rudix.ai
              </a>
              .
            </p>
          ),
        },
      ]}
    />
  );
}
