const CONSENT_STORAGE_KEY = "rudix.consent.v1";

/**
 * Bump this string when cookie categories or data collected change.
 * A version mismatch causes the banner to re-prompt the user.
 */
export const CONSENT_POLICY_VERSION = "1.0";

export type ConsentDecisions = {
  functional: boolean;
  analytics: boolean;
};

export type ConsentRecord = {
  policyVersion: string;
  timestamp: number;
  decisions: ConsentDecisions;
};

export function createDefaultConsentDecisions(): ConsentDecisions {
  return { functional: true, analytics: false };
}

function isValidConsentRecord(value: unknown): value is ConsentRecord {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  if (typeof c.policyVersion !== "string") return false;
  if (typeof c.timestamp !== "number") return false;
  if (typeof c.decisions !== "object" || c.decisions === null) return false;
  const d = c.decisions as Record<string, unknown>;
  return typeof d.functional === "boolean" && typeof d.analytics === "boolean";
}

export function readConsentRecord(): ConsentRecord | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isValidConsentRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeConsentRecord(record: ConsentRecord): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // ignore storage errors
  }
}

export function clearConsentRecord(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(CONSENT_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function hasCurrentConsent(): boolean {
  const record = readConsentRecord();
  return record !== null && record.policyVersion === CONSENT_POLICY_VERSION;
}
