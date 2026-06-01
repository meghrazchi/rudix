import type { AppRole } from "@/lib/auth-session";

export type OnboardingStepId =
  | "create_workspace"
  | "upload_document"
  | "wait_for_indexing"
  | "invite_team"
  | "ask_question"
  | "inspect_citations"
  | "review_security";

export type OnboardingStep = {
  id: OnboardingStepId;
  title: string;
  description: string;
  href: string | null;
  actionLabel: string | null;
  requiresRoles: AppRole[] | null;
  autoDetectable: boolean;
};

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  {
    id: "create_workspace",
    title: "Create your workspace",
    description: "Your organization workspace is ready.",
    href: null,
    actionLabel: null,
    requiresRoles: null,
    autoDetectable: true,
  },
  {
    id: "upload_document",
    title: "Upload your first document",
    description: "Add a PDF, DOCX, or text file to your knowledge base.",
    href: "/documents",
    actionLabel: "Go to Documents",
    requiresRoles: null,
    autoDetectable: true,
  },
  {
    id: "wait_for_indexing",
    title: "Wait for indexing",
    description: "Rudix processes and embeds your document for AI search.",
    href: "/documents",
    actionLabel: "Check status",
    requiresRoles: null,
    autoDetectable: true,
  },
  {
    id: "invite_team",
    title: "Invite your team",
    description: "Add members to collaborate in this workspace.",
    href: "/settings?tab=organization",
    actionLabel: "Manage team",
    requiresRoles: ["owner", "admin"],
    autoDetectable: false,
  },
  {
    id: "ask_question",
    title: "Ask your first question",
    description: "Chat with your knowledge base to get grounded answers.",
    href: "/chat",
    actionLabel: "Go to Chat",
    requiresRoles: null,
    autoDetectable: true,
  },
  {
    id: "inspect_citations",
    title: "Inspect citations",
    description:
      "Click a source citation to verify where the answer came from.",
    href: "/chat",
    actionLabel: "Open Chat",
    requiresRoles: null,
    autoDetectable: false,
  },
  {
    id: "review_security",
    title: "Review security settings",
    description: "Configure sessions, policies, and AI safety posture.",
    href: "/settings?tab=security",
    actionLabel: "Go to Security",
    requiresRoles: null,
    autoDetectable: false,
  },
] as const;

export type OnboardingState = {
  version: 1;
  dismissed: boolean;
  manuallyCompleted: OnboardingStepId[];
  tourSeen: boolean;
};

export type AutoDetectedCompletions = {
  hasOrganization: boolean;
  hasDocuments: boolean;
  hasIndexedDocuments: boolean;
  hasChatSessions: boolean;
};

const ONBOARDING_STORAGE_PREFIX = "rudix.onboarding.v1";

function storageKey(userId: string): string {
  return `${ONBOARDING_STORAGE_PREFIX}.${userId}`;
}

export function createDefaultOnboardingState(): OnboardingState {
  return {
    version: 1,
    dismissed: false,
    manuallyCompleted: [],
    tourSeen: false,
  };
}

function isValidOnboardingState(value: unknown): value is OnboardingState {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<OnboardingState>;
  return (
    candidate.version === 1 &&
    typeof candidate.dismissed === "boolean" &&
    Array.isArray(candidate.manuallyCompleted) &&
    typeof candidate.tourSeen === "boolean"
  );
}

export function readOnboardingState(userId: string): OnboardingState {
  if (typeof window === "undefined") return createDefaultOnboardingState();
  try {
    const raw = window.localStorage.getItem(storageKey(userId));
    if (!raw) return createDefaultOnboardingState();
    const parsed = JSON.parse(raw) as unknown;
    if (!isValidOnboardingState(parsed)) return createDefaultOnboardingState();
    return parsed;
  } catch {
    return createDefaultOnboardingState();
  }
}

export function writeOnboardingState(
  userId: string,
  state: OnboardingState,
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(state));
  } catch {
    // Ignore storage errors
  }
}

export function resolveVisibleSteps(role: AppRole): OnboardingStep[] {
  return ONBOARDING_STEPS.filter(
    (step) => step.requiresRoles === null || step.requiresRoles.includes(role),
  );
}

export function isStepComplete(
  stepId: OnboardingStepId,
  autoDetected: AutoDetectedCompletions,
  manuallyCompleted: OnboardingStepId[],
): boolean {
  if (manuallyCompleted.includes(stepId)) return true;

  switch (stepId) {
    case "create_workspace":
      return autoDetected.hasOrganization;
    case "upload_document":
      return autoDetected.hasDocuments;
    case "wait_for_indexing":
      return autoDetected.hasIndexedDocuments;
    case "ask_question":
      return autoDetected.hasChatSessions;
    default:
      return false;
  }
}

export function countIncompleteSteps(
  role: AppRole,
  autoDetected: AutoDetectedCompletions,
  manuallyCompleted: OnboardingStepId[],
): number {
  const steps = resolveVisibleSteps(role);
  return steps.filter(
    (step) => !isStepComplete(step.id, autoDetected, manuallyCompleted),
  ).length;
}
