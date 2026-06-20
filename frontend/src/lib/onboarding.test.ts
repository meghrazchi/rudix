import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  applyServerReset,
  countIncompleteSteps,
  createDefaultOnboardingState,
  isStepComplete,
  readOnboardingState,
  resolveVisibleSteps,
  writeOnboardingState,
  type AutoDetectedCompletions,
  type OnboardingState,
} from "@/lib/onboarding";

const ALL_DETECTED: AutoDetectedCompletions = {
  hasOrganization: true,
  hasDocuments: true,
  hasIndexedDocuments: true,
  hasChatSessions: true,
};

const NONE_DETECTED: AutoDetectedCompletions = {
  hasOrganization: false,
  hasDocuments: false,
  hasIndexedDocuments: false,
  hasChatSessions: false,
};

describe("createDefaultOnboardingState", () => {
  it("returns a valid default state", () => {
    const state = createDefaultOnboardingState();
    expect(state.version).toBe(1);
    expect(state.dismissed).toBe(false);
    expect(state.manuallyCompleted).toEqual([]);
    expect(state.tourSeen).toBe(false);
    expect(state.acknowledgedResetAt).toBeNull();
  });
});

describe("resolveVisibleSteps", () => {
  it("returns all steps for owner", () => {
    const steps = resolveVisibleSteps("owner");
    expect(steps.map((s) => s.id)).toContain("invite_team");
  });

  it("excludes role-restricted steps for viewer", () => {
    const steps = resolveVisibleSteps("viewer");
    expect(steps.map((s) => s.id)).not.toContain("invite_team");
  });

  it("excludes role-restricted steps for member", () => {
    const steps = resolveVisibleSteps("member");
    expect(steps.map((s) => s.id)).not.toContain("invite_team");
  });
});

describe("isStepComplete", () => {
  it("marks create_workspace complete when org exists", () => {
    expect(isStepComplete("create_workspace", ALL_DETECTED, [])).toBe(true);
    expect(isStepComplete("create_workspace", NONE_DETECTED, [])).toBe(false);
  });

  it("marks upload_document complete when docs exist", () => {
    expect(isStepComplete("upload_document", ALL_DETECTED, [])).toBe(true);
    expect(isStepComplete("upload_document", NONE_DETECTED, [])).toBe(false);
  });

  it("marks wait_for_indexing complete when indexed docs exist", () => {
    expect(isStepComplete("wait_for_indexing", ALL_DETECTED, [])).toBe(true);
    expect(
      isStepComplete("wait_for_indexing", { ...NONE_DETECTED, hasDocuments: true }, []),
    ).toBe(false);
  });

  it("marks ask_question complete when chat sessions exist", () => {
    expect(isStepComplete("ask_question", ALL_DETECTED, [])).toBe(true);
    expect(isStepComplete("ask_question", NONE_DETECTED, [])).toBe(false);
  });

  it("marks non-auto-detectable step complete when manually completed", () => {
    expect(isStepComplete("invite_team", NONE_DETECTED, ["invite_team"])).toBe(true);
    expect(isStepComplete("inspect_citations", NONE_DETECTED, ["inspect_citations"])).toBe(true);
    expect(isStepComplete("review_security", NONE_DETECTED, [])).toBe(false);
  });
});

describe("countIncompleteSteps", () => {
  it("counts 0 when all auto-detected and manually completed", () => {
    const count = countIncompleteSteps("owner", ALL_DETECTED, [
      "invite_team",
      "inspect_citations",
      "review_security",
    ]);
    expect(count).toBe(0);
  });

  it("counts correctly when nothing is done", () => {
    const ownerSteps = resolveVisibleSteps("owner");
    const count = countIncompleteSteps("owner", NONE_DETECTED, []);
    expect(count).toBe(ownerSteps.length);
  });
});

describe("readOnboardingState / writeOnboardingState", () => {
  const userId = "user-test-123";

  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns default state when nothing is stored", () => {
    const state = readOnboardingState(userId);
    expect(state).toEqual(createDefaultOnboardingState());
  });

  it("round-trips a written state correctly", () => {
    const custom: OnboardingState = {
      version: 1,
      dismissed: true,
      manuallyCompleted: ["invite_team", "inspect_citations"],
      tourSeen: true,
      acknowledgedResetAt: "2026-06-23T10:00:00Z",
    };
    writeOnboardingState(userId, custom);
    const read = readOnboardingState(userId);
    expect(read).toEqual(custom);
  });

  it("handles corrupted storage gracefully", () => {
    window.localStorage.setItem("rudix.onboarding.v1." + userId, "NOT_JSON{{");
    const state = readOnboardingState(userId);
    expect(state).toEqual(createDefaultOnboardingState());
  });

  it("migrates legacy state missing acknowledgedResetAt", () => {
    const legacy = {
      version: 1,
      dismissed: false,
      manuallyCompleted: [],
      tourSeen: false,
      // no acknowledgedResetAt field
    };
    window.localStorage.setItem(
      "rudix.onboarding.v1." + userId,
      JSON.stringify(legacy),
    );
    const state = readOnboardingState(userId);
    expect(state.acknowledgedResetAt).toBeNull();
  });
});

describe("applyServerReset", () => {
  const base = createDefaultOnboardingState();

  it("returns unchanged state when no server reset", () => {
    const state: OnboardingState = { ...base, dismissed: true };
    expect(applyServerReset(state, null)).toBe(state);
  });

  it("returns unchanged state when reset already acknowledged", () => {
    const state: OnboardingState = {
      ...base,
      dismissed: true,
      acknowledgedResetAt: "2026-06-23T10:00:00Z",
    };
    expect(applyServerReset(state, "2026-06-23T10:00:00Z")).toBe(state);
  });

  it("resets state when server reset_at is newer than acknowledged", () => {
    const state: OnboardingState = {
      ...base,
      dismissed: true,
      manuallyCompleted: ["invite_team"],
      tourSeen: true,
      acknowledgedResetAt: null,
    };
    const next = applyServerReset(state, "2026-06-23T12:00:00Z");
    expect(next).not.toBe(state);
    expect(next.dismissed).toBe(false);
    expect(next.manuallyCompleted).toEqual([]);
    expect(next.tourSeen).toBe(false);
    expect(next.acknowledgedResetAt).toBe("2026-06-23T12:00:00Z");
  });

  it("updates acknowledgedResetAt when reset differs from last ack", () => {
    const state: OnboardingState = {
      ...base,
      acknowledgedResetAt: "2026-06-01T00:00:00Z",
    };
    const next = applyServerReset(state, "2026-06-23T12:00:00Z");
    expect(next.acknowledgedResetAt).toBe("2026-06-23T12:00:00Z");
  });
});
