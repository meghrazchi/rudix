"use client";

import {
  type AiResponsePolicyResponse,
  type CitationMode,
  type CreateAiResponsePolicyRequest,
  type DisclaimerPosition,
  type NoAnswerBehavior,
  type PolicyOutcome,
  type StaleSourceBehavior,
} from "@/lib/api/ai-response-policy";

export type Tab = "policies" | "logs";

export type FormState = {
  policy_name: string;
  description: string;
  citation_mode: CitationMode;
  min_confidence_threshold: string;
  no_answer_behavior: NoAnswerBehavior;
  stale_source_behavior: StaleSourceBehavior;
  blocked_topics: string;
  allowed_topics: string;
  min_sources_required: string;
  disclaimer_text: string;
  disclaimer_position: DisclaimerPosition;
  refusal_message: string;
};

export type PanelState =
  | { kind: "idle" }
  | { kind: "create" }
  | { kind: "edit"; policy: AiResponsePolicyResponse }
  | { kind: "preview"; policy: AiResponsePolicyResponse };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export const CITATION_MODE_LABELS: Record<CitationMode, string> = {
  required: "Required",
  recommended: "Recommended",
  disabled: "Disabled",
};

export const NO_ANSWER_LABELS: Record<NoAnswerBehavior, string> = {
  refuse: "Refuse (safe refusal)",
  warn: "Warn (allow with warning)",
  allow: "Allow (no restriction)",
};

export const STALE_LABELS: Record<StaleSourceBehavior, string> = {
  warn: "Warn",
  refuse: "Refuse",
  ignore: "Ignore",
};

export const OUTCOME_COLORS: Record<PolicyOutcome, string> = {
  allowed: "bg-green-100 text-green-800",
  blocked: "bg-red-100 text-red-800",
  warned: "bg-yellow-100 text-yellow-800",
};

export function topicsFromRaw(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function topicsToRaw(topics: string[] | null | undefined): string {
  return (topics ?? []).join(", ");
}

export function emptyForm(): FormState {
  return {
    policy_name: "",
    description: "",
    citation_mode: "recommended",
    min_confidence_threshold: "",
    no_answer_behavior: "warn",
    stale_source_behavior: "warn",
    blocked_topics: "",
    allowed_topics: "",
    min_sources_required: "",
    disclaimer_text: "",
    disclaimer_position: "prepend",
    refusal_message: "",
  };
}

export function policyToForm(policy: AiResponsePolicyResponse): FormState {
  return {
    policy_name: policy.policy_name,
    description: policy.description ?? "",
    citation_mode: policy.citation_mode,
    min_confidence_threshold:
      policy.min_confidence_threshold !== null
        ? String(policy.min_confidence_threshold)
        : "",
    no_answer_behavior: policy.no_answer_behavior,
    stale_source_behavior: policy.stale_source_behavior,
    blocked_topics: topicsToRaw(policy.blocked_topics),
    allowed_topics: topicsToRaw(policy.allowed_topics),
    min_sources_required:
      policy.min_sources_required !== null
        ? String(policy.min_sources_required)
        : "",
    disclaimer_text: policy.disclaimer_text ?? "",
    disclaimer_position: policy.disclaimer_position,
    refusal_message: policy.refusal_message ?? "",
  };
}

export function formToRequest(form: FormState): CreateAiResponsePolicyRequest {
  return {
    policy_name: form.policy_name.trim(),
    description: form.description.trim() || null,
    citation_mode: form.citation_mode,
    min_confidence_threshold: form.min_confidence_threshold
      ? parseFloat(form.min_confidence_threshold)
      : null,
    no_answer_behavior: form.no_answer_behavior,
    stale_source_behavior: form.stale_source_behavior,
    blocked_topics: topicsFromRaw(form.blocked_topics),
    allowed_topics: form.allowed_topics.trim()
      ? topicsFromRaw(form.allowed_topics)
      : null,
    min_sources_required: form.min_sources_required
      ? parseInt(form.min_sources_required, 10)
      : null,
    disclaimer_text: form.disclaimer_text.trim() || null,
    disclaimer_position: form.disclaimer_position,
    refusal_message: form.refusal_message.trim() || null,
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

export function OutcomeChip({ outcome }: { outcome: PolicyOutcome }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${OUTCOME_COLORS[outcome]}`}
    >
      {outcome.charAt(0).toUpperCase() + outcome.slice(1)}
    </span>
  );
}

export function PolicyStatusBadge({ isActive }: { isActive: boolean }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${
        isActive ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
      }`}
    >
      {isActive ? "Active" : "Inactive"}
    </span>
  );
}
