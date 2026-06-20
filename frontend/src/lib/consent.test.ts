import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  clearConsentRecord,
  CONSENT_POLICY_VERSION,
  createDefaultConsentDecisions,
  hasCurrentConsent,
  readConsentRecord,
  writeConsentRecord,
  type ConsentRecord,
} from "@/lib/consent";

describe("consent storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  describe("createDefaultConsentDecisions", () => {
    it("returns functional true, analytics false", () => {
      const d = createDefaultConsentDecisions();
      expect(d.functional).toBe(true);
      expect(d.analytics).toBe(false);
    });
  });

  describe("readConsentRecord", () => {
    it("returns null when nothing is stored", () => {
      expect(readConsentRecord()).toBeNull();
    });

    it("returns null when stored value is invalid JSON", () => {
      window.localStorage.setItem("rudix.consent.v1", "not-json");
      expect(readConsentRecord()).toBeNull();
    });

    it("returns null when stored value is missing required fields", () => {
      window.localStorage.setItem(
        "rudix.consent.v1",
        JSON.stringify({ policyVersion: "1.0" }),
      );
      expect(readConsentRecord()).toBeNull();
    });

    it("returns null when decisions are not booleans", () => {
      window.localStorage.setItem(
        "rudix.consent.v1",
        JSON.stringify({
          policyVersion: "1.0",
          timestamp: 1000,
          decisions: { functional: "yes", analytics: 1 },
        }),
      );
      expect(readConsentRecord()).toBeNull();
    });

    it("returns the stored record when valid", () => {
      const record: ConsentRecord = {
        policyVersion: "1.0",
        timestamp: 1_700_000_000_000,
        decisions: { functional: true, analytics: false },
      };
      window.localStorage.setItem("rudix.consent.v1", JSON.stringify(record));
      expect(readConsentRecord()).toEqual(record);
    });
  });

  describe("writeConsentRecord", () => {
    it("persists a record readable by readConsentRecord", () => {
      const record: ConsentRecord = {
        policyVersion: CONSENT_POLICY_VERSION,
        timestamp: Date.now(),
        decisions: { functional: true, analytics: true },
      };
      writeConsentRecord(record);
      expect(readConsentRecord()).toEqual(record);
    });
  });

  describe("clearConsentRecord", () => {
    it("removes the stored record", () => {
      const record: ConsentRecord = {
        policyVersion: CONSENT_POLICY_VERSION,
        timestamp: Date.now(),
        decisions: { functional: true, analytics: false },
      };
      writeConsentRecord(record);
      clearConsentRecord();
      expect(readConsentRecord()).toBeNull();
    });

    it("does not throw when nothing is stored", () => {
      expect(() => clearConsentRecord()).not.toThrow();
    });
  });

  describe("hasCurrentConsent", () => {
    it("returns false when nothing is stored", () => {
      expect(hasCurrentConsent()).toBe(false);
    });

    it("returns false when stored record has an older policy version", () => {
      const record: ConsentRecord = {
        policyVersion: "0.9",
        timestamp: Date.now(),
        decisions: { functional: true, analytics: false },
      };
      writeConsentRecord(record);
      expect(hasCurrentConsent()).toBe(false);
    });

    it("returns true when stored record matches current policy version", () => {
      const record: ConsentRecord = {
        policyVersion: CONSENT_POLICY_VERSION,
        timestamp: Date.now(),
        decisions: { functional: false, analytics: false },
      };
      writeConsentRecord(record);
      expect(hasCurrentConsent()).toBe(true);
    });
  });
});
