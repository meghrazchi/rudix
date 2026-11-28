"use client";

import { useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import type {
  ChatConfidenceExplanationResponse,
  ChatDebugResponse,
} from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";
import { trackFeatureEvent } from "@/lib/analytics";
import { ClaimSupportSection } from "@/components/chat/trust-panel/ClaimSupportSection";
import { CitationsSection } from "@/components/chat/trust-panel/CitationsSection";
import { ConfidenceSection } from "@/components/chat/trust-panel/ConfidenceSection";
import { ConflictSection } from "@/components/chat/trust-panel/ConflictSection";
import { GraphRagSection } from "@/components/chat/trust-panel/GraphRagSection";
import { ModelSection } from "@/components/chat/trust-panel/ModelSection";
import { PlannerCriticSection } from "@/components/chat/trust-panel/PlannerCriticSection";
import { PolicySection } from "@/components/chat/trust-panel/PolicySection";
import { QueryInterpretationSection } from "@/components/chat/trust-panel/QueryInterpretationSection";
import { RetrievalDiagnosticsSection } from "@/components/chat/trust-panel/RetrievalDiagnosticsSection";
import { RetrievalMethodSection } from "@/components/chat/trust-panel/RetrievalMethodSection";
import { SourceSelectionSection } from "@/components/chat/trust-panel/SourceSelectionSection";
import { ToolOrchestrationSection } from "@/components/chat/trust-panel/ToolOrchestrationSection";
import { TrustPanelHeader } from "@/components/chat/trust-panel/TrustPanelHeader";
import { TrustWarningsSection } from "@/components/chat/trust-panel/TrustWarningsSection";
import { VerificationSection } from "@/components/chat/trust-panel/VerificationSection";
import { answerModeBadge } from "@/components/chat/trust-panel/trust-badges";
import { buildRetrievalSummary } from "@/components/chat/trust-panel/trust-format";
import type { TrustPanelCitation } from "@/components/chat/trust-panel/trust-types";
import { buildTrustWarnings } from "@/components/chat/trust-panel/trust-warnings";

// Minimum props the trust panel needs — a deliberate subset of ChatTurn["response"].
export type TrustPanelProps = {
  messageId: string;
  confidenceScore: number;
  confidenceCategory: "low" | "medium" | "high";
  confidenceExplanation: ChatConfidenceExplanationResponse | null;
  citationValidationFailed: boolean;
  verificationFailed: boolean;
  sourceFreshnessWarning: boolean;
  sourceFreshnessWarningReason: string | null;
  policyApplied: boolean;
  policyOutcome: string | null;
  policyViolatedRules: string[];
  policyWarningFlags: string[];
  policyDisclaimer: string | null;
  citations: TrustPanelCitation[];
  debug: ChatDebugResponse | null;
  trustMetadata?: AnswerTrustMetadataResponse | null;
  showInterpretationDetails?: boolean;
  onOpenCitation: (citation: TrustPanelCitation) => void;
  hideHeader?: boolean;
  /** F316 — called when the user clicks "Report issue" from within the panel. */
  onReportIssue?: (context: {
    warnings: string[];
    traceId: string | null;
    trustScore: number;
    trustLevel: string | null;
  }) => void;
  /** F328 — called when the user wants to save this answer as a knowledge card. */
  onSaveAsKnowledgeCard?: () => void;
};

export function AnswerTrustPanel({
  messageId,
  confidenceScore,
  confidenceCategory,
  confidenceExplanation,
  citationValidationFailed,
  verificationFailed,
  sourceFreshnessWarning,
  sourceFreshnessWarningReason,
  policyApplied,
  policyOutcome,
  policyViolatedRules,
  policyWarningFlags,
  policyDisclaimer,
  citations,
  debug,
  trustMetadata,
  showInterpretationDetails = false,
  onOpenCitation,
  onReportIssue,
  onSaveAsKnowledgeCard,
  hideHeader = false,
}: TrustPanelProps) {
  const t = useTranslations("chat.trustPanel");
  const [diagnosticsMode, setDiagnosticsMode] = useState<"basic" | "expert">(
    "basic",
  );
  const [prevDiagnosticsKey, setPrevDiagnosticsKey] = useState({
    messageId,
    showInterpretationDetails,
  });
  if (
    prevDiagnosticsKey.messageId !== messageId ||
    prevDiagnosticsKey.showInterpretationDetails !== showInterpretationDetails
  ) {
    setPrevDiagnosticsKey({ messageId, showInterpretationDetails });
    setDiagnosticsMode("basic");
  }
  const graphUsed = debug?.graph_context_used ?? false;
  const graphEnabled = debug?.graph_context_enabled ?? false;
  const groundedVerification = trustMetadata?.grounded_verification ?? null;
  const trustCitations = trustMetadata?.citations ?? citations;
  const retrievalDiagnostics = trustMetadata?.retrieval ?? debug;
  const queryInterpretation = trustMetadata?.query_interpretation ?? null;
  const answerModeBadgeRecord = answerModeBadge(
    queryInterpretation?.answer_mode ?? null,
    t,
  );
  const retrievalSummary =
    retrievalDiagnostics != null
      ? buildRetrievalSummary(
          {
            retrieval_candidate_count:
              retrievalDiagnostics.retrieval_candidate_count ??
              retrievalDiagnostics.retrieval_count,
            retrieval_count: retrievalDiagnostics.retrieval_count,
            selected_count: retrievalDiagnostics.selected_count,
            top_k: retrievalDiagnostics.top_k,
            search_mode: retrievalDiagnostics.search_mode,
            source_scope_label: retrievalDiagnostics.source_scope_label,
            retrieval_profile_name: retrievalDiagnostics.retrieval_profile_name,
            retrieval_profile_scope:
              retrievalDiagnostics.retrieval_profile_scope,
            retrieval_profile_source:
              retrievalDiagnostics.retrieval_profile_source,
            rerank_applied: retrievalDiagnostics.rerank_applied,
            rerank_fallback_used: retrievalDiagnostics.rerank_fallback_used,
            rerank_fallback_reason: retrievalDiagnostics.rerank_fallback_reason,
          },
          t,
        )
      : null;
  const verificationApplied =
    groundedVerification?.applied ??
    debug?.grounded_verification_applied ??
    false;

  // F317 — track trust panel open
  useEffect(() => {
    void trackFeatureEvent("feature.chat.trust_panel_opened", {
      surface: "app",
      route: "/chat",
      pageKey: "chat",
      featureArea: "chat",
      entityId: messageId,
      status: confidenceCategory,
      dedupeKey: `chat-trust-panel-${messageId}`,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messageId]);

  useEffect(() => {
    if (!retrievalSummary) return;
    void trackFeatureEvent("feature.chat.retrieval_diagnostics_viewed", {
      surface: "app",
      route: "/chat",
      pageKey: "chat",
      featureArea: "chat",
      entityId: messageId,
      status: diagnosticsMode,
      source: "trust_panel",
      dedupeKey: `chat-retrieval-diagnostics-${messageId}-${diagnosticsMode}`,
    });
  }, [diagnosticsMode, messageId, retrievalSummary]);

  const warnings = buildTrustWarnings({
    confidenceCategory,
    citationValidationFailed,
    verificationFailed,
    sourceFreshnessWarning,
    sourceFreshnessWarningReason,
    policyDisclaimer,
    trustMetadata,
    trustCitations,
    debug,
    t,
  });
  const conflictRecord = trustMetadata?.conflict ?? null;
  const showModelSection =
    debug && (debug.llm_model || debug.embedding_model || debug.llm_provider);
  const canShowExpertDiagnostics =
    Boolean(showInterpretationDetails) && diagnosticsMode === "expert";

  return (
    <div
      data-testid={`trust-panel-${messageId}`}
      className={`text-[#2f2a46] ${
        hideHeader
          ? "mt-0 overflow-visible rounded-none border-0 bg-transparent shadow-none"
          : "mt-2 overflow-hidden rounded-[24px] border border-[#d7d4e8] bg-[#fcf8ff] shadow-[0_18px_50px_rgba(53,37,205,0.08)]"
      }`}
    >
      <TrustPanelHeader
        messageId={messageId}
        hideHeader={hideHeader}
        showInterpretationDetails={showInterpretationDetails}
        diagnosticsMode={diagnosticsMode}
        setDiagnosticsMode={setDiagnosticsMode}
        answerModeBadgeRecord={answerModeBadgeRecord}
        warnings={warnings}
        confidenceScore={confidenceScore}
        trustMetadata={trustMetadata}
        debug={debug}
        onSaveAsKnowledgeCard={onSaveAsKnowledgeCard}
        onReportIssue={onReportIssue}
      />

      {/* Warnings */}
      <TrustWarningsSection warnings={warnings} messageId={messageId} />

      <SourceSelectionSection
        retrievalSummary={retrievalSummary}
        retrievalDiagnostics={retrievalDiagnostics}
      />

      {/* Confidence */}
      <ConfidenceSection
        confidenceScore={confidenceScore}
        confidenceCategory={confidenceCategory}
        confidenceExplanation={confidenceExplanation}
        trustMetadata={trustMetadata}
      />

      {/* Source Conflict */}
      <ConflictSection conflictRecord={conflictRecord} />

      {/* Claim support */}
      <ClaimSupportSection
        groundedVerification={groundedVerification}
        trustCitations={trustCitations}
        onOpenCitation={onOpenCitation}
      />

      {/* Citations */}
      <CitationsSection
        trustCitations={trustCitations}
        messageId={messageId}
        onOpenCitation={onOpenCitation}
      />

      {/* Retrieval Diagnostics */}
      {canShowExpertDiagnostics && retrievalDiagnostics ? (
        <RetrievalDiagnosticsSection
          retrievalDiagnostics={retrievalDiagnostics}
          debug={debug}
        />
      ) : null}

      {showInterpretationDetails && queryInterpretation ? (
        <QueryInterpretationSection queryInterpretation={queryInterpretation} />
      ) : null}

      {/* Model & Prompt */}
      {debug && showModelSection ? <ModelSection debug={debug} /> : null}

      {/* Knowledge Graph */}
      {graphUsed || (graphEnabled && debug?.graph_context_unavailable) ? (
        <GraphRagSection debug={debug} />
      ) : null}

      {/* Grounded Verification */}
      {verificationApplied ? <VerificationSection debug={debug} /> : null}

      {/* Policy */}
      {policyApplied ? (
        <PolicySection
          policyOutcome={policyOutcome}
          policyViolatedRules={policyViolatedRules}
          policyWarningFlags={policyWarningFlags}
        />
      ) : null}

      {/* Planner / Critic / Refiner (F339) */}
      <PlannerCriticSection
        plannerCritic={trustMetadata?.planner_critic ?? null}
      />

      {/* Dynamic retrieval method (F341) */}
      <RetrievalMethodSection
        retrievalMethod={trustMetadata?.retrieval_method ?? null}
      />

      {/* Adaptive tool orchestration (F342) */}
      <ToolOrchestrationSection
        toolOrchestration={trustMetadata?.tool_orchestration ?? null}
      />
    </div>
  );
}
