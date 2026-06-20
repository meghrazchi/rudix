import { LegalPageLayout } from "./LegalPageLayout";

export function CookiePolicyPage() {
  return (
    <LegalPageLayout
      title="Cookie Policy"
      version="0.1"
      effectiveDate="2026-06-20"
      sections={[
        {
          heading: "1. What Are Cookies",
          body: (
            <p>
              Cookies are small text files stored in your browser when you visit
              a website. We also use browser&rsquo;s localStorage for certain
              persistent preferences. This policy explains what we store, why,
              and how you can control it.
            </p>
          ),
        },
        {
          heading: "2. Cookies We Use",
          body: (
            <>
              <p>
                <strong>Session cookie.</strong> An HTTP-only, secure cookie
                stores your authenticated session token. It is required for
                login and is cleared when you sign out or your session expires.
                This cookie cannot be controlled through browser cookie settings
                without signing out.
              </p>
              <p>
                <strong>CSRF protection cookie.</strong> A same-site cookie used
                to protect form submissions from cross-site request forgery
                attacks. It is set automatically when you access the application
                and cleared with your session.
              </p>
              <p>
                <strong>Language preference (localStorage).</strong> Your
                selected display language (English, German, French, or Spanish)
                is stored in browser localStorage under the key{" "}
                <code>rudix_lang</code>. This is a preference value only and
                contains no personal data.
              </p>
              <p>
                <strong>Chat scope preference (localStorage).</strong> Your last
                selected chat scope setting is stored in localStorage to restore
                it across sessions. This contains no personal data.
              </p>
            </>
          ),
        },
        {
          heading: "3. What We Do Not Use",
          body: (
            <p>
              We do not use third-party advertising cookies, cross-site tracking
              pixels, or analytics services that place cookies in your browser.
              We do not sell or share cookie data with advertising networks.
            </p>
          ),
        },
        {
          heading: "4. How to Control Cookies",
          body: (
            <>
              <p>
                You can delete browser cookies and localStorage data through
                your browser settings at any time. Deleting the session cookie
                will sign you out of the application. Deleting localStorage will
                reset language and preference settings.
              </p>
              <p>
                Because all cookies we set are strictly necessary for the
                Service to function correctly, we do not display a cookie
                consent banner at this time. [LEGAL REVIEW REQUIRED: confirm
                whether a consent banner is required under applicable law for
                your deployment jurisdiction.]
              </p>
            </>
          ),
        },
        {
          heading: "5. Changes to This Policy",
          body: (
            <p>
              If we introduce new cookies or tracking technologies, we will
              update this policy and, where required, obtain consent. The
              version number and effective date at the top of this page reflect
              the latest revision.
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
              . [LEGAL REVIEW REQUIRED: verify contact address.]
            </p>
          ),
        },
      ]}
    />
  );
}
