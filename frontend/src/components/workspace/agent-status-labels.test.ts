import { describe, expect, it } from "vitest";

import ar from "@/i18n/messages/ar.json";
import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import es from "@/i18n/messages/es.json";
import fa from "@/i18n/messages/fa.json";
import fr from "@/i18n/messages/fr.json";

// AgentWorkspacePage's StatusBadge renders `agentWorkspace.statuses.<status>`
// for runs, steps, tool calls and approvals. These sets mirror the backend
// CHECK constraints in backend/app/models/agent.py.
const BACKEND_STATUSES = {
  run: [
    "queued",
    "planning",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
  ],
  step: [
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "skipped",
    "cancelled",
  ],
  toolCall: ["queued", "running", "succeeded", "failed", "cancelled"],
  approval: [
    "pending",
    "approved",
    "rejected",
    "changes_requested",
    "expired",
    "cancelled",
  ],
} as const;

const LOCALES = { en, de, es, fr, ar, fa } as const;

describe("agent workspace status labels", () => {
  const allStatuses = [...new Set(Object.values(BACKEND_STATUSES).flat())];

  for (const [locale, messages] of Object.entries(LOCALES)) {
    it(`${locale} labels every backend agent status as plain text`, () => {
      const labels = messages.agentWorkspace.statuses as Record<string, string>;
      for (const status of allStatuses) {
        expect(labels[status], `${locale}: ${status}`).toBeTruthy();
        // A badge label takes no ICU arguments.
        expect(labels[status], `${locale}: ${status}`).not.toMatch(/[{}]/);
      }
    });
  }
});
