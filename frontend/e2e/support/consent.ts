import {
  CONSENT_POLICY_VERSION,
  createDefaultConsentDecisions,
  type ConsentRecord,
} from "../../src/lib/consent";

/** localStorage key used by src/lib/consent.ts. */
export const CONSENT_STORAGE_KEY = "rudix.consent.v1";

/**
 * Storage state for a returning visitor who already answered the cookie
 * banner (essential + functional only, the app's defaults).
 *
 * The banner (79ca72a, rudix#182) is a fixed, modal bottom sheet that
 * intercepts pointer events on first visit. Specs that exercise other
 * features start as a returning visitor; e2e/cookie-consent.spec.ts covers
 * the first-visit banner itself by clearing this state.
 */
export function consentedStorageState(origin: string): {
  cookies: [];
  origins: Array<{
    origin: string;
    localStorage: Array<{ name: string; value: string }>;
  }>;
} {
  const record: ConsentRecord = {
    policyVersion: CONSENT_POLICY_VERSION,
    timestamp: Date.parse("2026-01-01T00:00:00Z"),
    decisions: createDefaultConsentDecisions(),
  };
  return {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [
          { name: CONSENT_STORAGE_KEY, value: JSON.stringify(record) },
        ],
      },
    ],
  };
}
