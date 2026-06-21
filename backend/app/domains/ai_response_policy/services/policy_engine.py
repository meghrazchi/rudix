"""AI response policy engine — evaluation service (F268).

Resolves the effective policy for an org/collection context and evaluates
chat questions and generated answers against that policy.

Evaluation is split into two phases:

1. Pre-generation: topic blocking checks on the raw question.
2. Post-generation: citation, confidence, and stale-source checks on the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.ai_response_policy import (
    CollectionAiResponsePolicyOverride,
    OrgAiResponsePolicy,
)

_DEFAULT_REFUSAL = "I'm unable to provide an answer due to your organization's content policy."


@dataclass
class EffectivePolicy:
    """Merged policy view after applying collection overrides."""

    policy_id: str | None
    source: str  # "org" | "collection" | "none"
    citation_mode: str = "recommended"
    min_confidence_threshold: float | None = None
    no_answer_behavior: str = "warn"
    grounded_verification_mode: str = "off"
    grounded_verification_threshold: float | None = None
    stale_source_behavior: str = "warn"
    blocked_topics: list[str] = field(default_factory=list)
    allowed_topics: list[str] | None = None
    min_sources_required: int | None = None
    disclaimer_text: str | None = None
    disclaimer_position: str = "prepend"
    refusal_message: str | None = None


@dataclass
class PolicyEvaluationResult:
    blocked: bool = False
    warned: bool = False
    violated_rules: list[str] = field(default_factory=list)
    warning_flags: list[str] = field(default_factory=list)
    refusal_message: str | None = None
    disclaimer_text: str | None = None
    disclaimer_position: str = "prepend"
    policy_id: str | None = None
    policy_source: str = "none"

    @property
    def outcome(self) -> str:
        if self.blocked:
            return "blocked"
        if self.warned:
            return "warned"
        return "allowed"


class AiResponsePolicyEngine:
    """Stateless policy evaluation engine.

    All methods operate on the resolved ``EffectivePolicy`` so they can be
    called without a DB session during the hot path.
    """

    # ------------------------------------------------------------------
    # Policy resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        org_policy: OrgAiResponsePolicy | None,
        collection_override: CollectionAiResponsePolicyOverride | None = None,
    ) -> EffectivePolicy:
        """Merge org policy with optional collection override into a single view."""
        if org_policy is None or not org_policy.is_active:
            return EffectivePolicy(policy_id=None, source="none")

        ep = EffectivePolicy(
            policy_id=str(org_policy.id),
            source="org",
            citation_mode=org_policy.citation_mode,
            min_confidence_threshold=org_policy.min_confidence_threshold,
            no_answer_behavior=org_policy.no_answer_behavior,
            grounded_verification_mode=org_policy.grounded_verification_mode,
            grounded_verification_threshold=org_policy.grounded_verification_threshold,
            stale_source_behavior=org_policy.stale_source_behavior,
            blocked_topics=list(org_policy.blocked_topics_json or []),
            allowed_topics=list(org_policy.allowed_topics_json)
            if org_policy.allowed_topics_json is not None
            else None,
            min_sources_required=org_policy.min_sources_required,
            disclaimer_text=org_policy.disclaimer_text,
            disclaimer_position=org_policy.disclaimer_position,
            refusal_message=org_policy.refusal_message,
        )

        if collection_override is not None:
            ep.source = "collection"
            if collection_override.citation_mode is not None:
                ep.citation_mode = collection_override.citation_mode
            if collection_override.min_confidence_threshold is not None:
                ep.min_confidence_threshold = collection_override.min_confidence_threshold
            if collection_override.no_answer_behavior is not None:
                ep.no_answer_behavior = collection_override.no_answer_behavior
            if collection_override.grounded_verification_mode is not None:
                ep.grounded_verification_mode = collection_override.grounded_verification_mode
            if collection_override.grounded_verification_threshold is not None:
                ep.grounded_verification_threshold = (
                    collection_override.grounded_verification_threshold
                )
            if collection_override.stale_source_behavior is not None:
                ep.stale_source_behavior = collection_override.stale_source_behavior
            if collection_override.blocked_topics_json is not None:
                ep.blocked_topics = list(collection_override.blocked_topics_json)
            if collection_override.allowed_topics_json is not None:
                ep.allowed_topics = list(collection_override.allowed_topics_json)
            if collection_override.min_sources_required is not None:
                ep.min_sources_required = collection_override.min_sources_required
            if collection_override.disclaimer_text is not None:
                ep.disclaimer_text = collection_override.disclaimer_text
            if collection_override.refusal_message is not None:
                ep.refusal_message = collection_override.refusal_message

        return ep

    # ------------------------------------------------------------------
    # Phase 1: Pre-generation check (topic blocking)
    # ------------------------------------------------------------------

    def evaluate_pre_generation(
        self,
        question: str,
        effective_policy: EffectivePolicy,
    ) -> PolicyEvaluationResult:
        """Check the user's question against topic allow/block lists.

        Returns a result with ``blocked=True`` when the question must be
        refused before any retrieval or LLM call is made.
        """
        result = PolicyEvaluationResult(
            policy_id=effective_policy.policy_id,
            policy_source=effective_policy.source,
            disclaimer_text=effective_policy.disclaimer_text,
            disclaimer_position=effective_policy.disclaimer_position,
            refusal_message=effective_policy.refusal_message or _DEFAULT_REFUSAL,
        )

        if effective_policy.source == "none":
            return result

        question_lower = question.lower()

        # Blocked topic check — any match → refuse
        for topic in effective_policy.blocked_topics:
            if topic.strip().lower() in question_lower:
                result.blocked = True
                result.violated_rules.append(f"blocked_topic:{topic}")

        # Allowed topic check — if set and no match → refuse
        if not result.blocked and effective_policy.allowed_topics is not None:
            if not any(
                t.strip().lower() in question_lower for t in effective_policy.allowed_topics
            ):
                result.blocked = True
                result.violated_rules.append("topic_not_in_allowed_list")

        return result

    # ------------------------------------------------------------------
    # Phase 2: Post-generation check (citations, confidence, freshness)
    # ------------------------------------------------------------------

    def evaluate_post_generation(
        self,
        *,
        confidence_score: float | None,
        citation_count: int,
        stale_source_count: int,
        not_found: bool,
        effective_policy: EffectivePolicy,
    ) -> PolicyEvaluationResult:
        """Evaluate the generated answer against citation, confidence, and freshness rules."""
        result = PolicyEvaluationResult(
            policy_id=effective_policy.policy_id,
            policy_source=effective_policy.source,
            disclaimer_text=effective_policy.disclaimer_text,
            disclaimer_position=effective_policy.disclaimer_position,
            refusal_message=effective_policy.refusal_message or _DEFAULT_REFUSAL,
        )

        if effective_policy.source == "none":
            return result

        # Citation mode enforcement
        if effective_policy.citation_mode == "required" and citation_count == 0:
            result.violated_rules.append("citation_required_but_missing")
            result.blocked = True

        # Minimum sources gate
        if (
            effective_policy.min_sources_required is not None
            and citation_count < effective_policy.min_sources_required
        ):
            result.violated_rules.append(
                f"min_sources_required:{effective_policy.min_sources_required}"
            )
            result.blocked = True

        # Confidence threshold enforcement
        if (
            effective_policy.min_confidence_threshold is not None
            and confidence_score is not None
            and confidence_score < effective_policy.min_confidence_threshold
        ):
            rule = f"confidence_below_threshold:{effective_policy.min_confidence_threshold:.2f}"
            if effective_policy.no_answer_behavior == "refuse" or not_found:
                result.violated_rules.append(rule)
                result.blocked = True
            else:
                result.warning_flags.append(rule)
                result.warned = True

        # not_found signal
        if not_found and effective_policy.no_answer_behavior == "refuse":
            if "not_found_refused" not in result.violated_rules:
                result.violated_rules.append("not_found_refused")
                result.blocked = True
        elif not_found and effective_policy.no_answer_behavior == "warn":
            result.warning_flags.append("not_found_warning")
            if not result.blocked:
                result.warned = True

        # Stale source enforcement
        if stale_source_count > 0:
            if effective_policy.stale_source_behavior == "refuse":
                result.violated_rules.append(f"stale_sources:{stale_source_count}")
                result.blocked = True
            elif effective_policy.stale_source_behavior == "warn":
                result.warning_flags.append(f"stale_sources_warning:{stale_source_count}")
                if not result.blocked:
                    result.warned = True

        return result

    # ------------------------------------------------------------------
    # Disclaimer injection
    # ------------------------------------------------------------------

    def apply_disclaimer(self, answer: str, result: PolicyEvaluationResult) -> str:
        """Prepend or append the disclaimer text to the answer when present."""
        if not result.disclaimer_text or result.blocked:
            return answer
        sep = "\n\n"
        if result.disclaimer_position == "append":
            return f"{answer}{sep}{result.disclaimer_text}"
        return f"{result.disclaimer_text}{sep}{answer}"
