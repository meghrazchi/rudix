import type { TrustT } from "@/components/chat/trust-panel/trust-types";
import type { QueryInterpretationRecord } from "@/lib/api/trust_metadata";

export function pct(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "N/A";
  return `${(v * 100).toFixed(1)}%`;
}

export function score(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "N/A";
  return v.toFixed(3);
}

export function confidenceBarClass(
  category: "low" | "medium" | "high",
): string {
  if (category === "high") return "bg-emerald-500";
  if (category === "medium") return "bg-amber-400";
  return "bg-rose-400";
}

export function confidenceBadgeClass(
  category: "low" | "medium" | "high",
): string {
  if (category === "high")
    return "inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-800";
  if (category === "medium")
    return "inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-800";
  return "inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-800";
}

export function reasonImpactIcon(impact: "positive" | "negative" | "neutral"): {
  icon: string;
  cls: string;
} {
  if (impact === "positive")
    return { icon: "arrow_upward", cls: "text-emerald-600" };
  if (impact === "negative")
    return { icon: "arrow_downward", cls: "text-rose-500" };
  return { icon: "remove", cls: "text-[#9d98b5]" };
}

export function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return null;
  }
}

export function queryComplexityLabel(
  complexity: QueryInterpretationRecord["complexity"],
  t: TrustT,
): string {
  if (complexity === "multi_part") return t("complexity.multiPart");
  if (complexity === "simple") return t("complexity.simple");
  if (complexity === "complex") return t("complexity.complex");
  return complexity;
}

export function joinParts(parts: Array<string | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(" · ");
}

export function formatRange(
  min: number | null | undefined,
  max: number | null | undefined,
  t: TrustT,
): string {
  if (typeof min !== "number" && typeof max !== "number") return t("na");
  if (typeof min === "number" && typeof max === "number") {
    return `${score(min)} - ${score(max)}`;
  }
  if (typeof min === "number") return t("range.from", { value: score(min) });
  return t("range.upTo", { value: score(max) });
}

export function buildRetrievalSummary(
  retrieval: {
    retrieval_candidate_count?: number;
    retrieval_count: number;
    selected_count: number;
    top_k?: number;
    search_mode?: string | null;
    source_scope_label?: string | null;
    retrieval_profile_name?: string | null;
    retrieval_profile_scope?: string | null;
    retrieval_profile_source?: string | null;
    rerank_applied: boolean;
    rerank_fallback_used?: boolean;
    rerank_fallback_reason?: string | null;
  },
  t: TrustT,
): string {
  const candidateCount =
    retrieval.retrieval_candidate_count ?? retrieval.retrieval_count;
  const scope =
    retrieval.source_scope_label ?? retrieval.retrieval_profile_scope;
  const profile = retrieval.retrieval_profile_name
    ? `${retrieval.retrieval_profile_name}${
        retrieval.retrieval_profile_source
          ? ` (${retrieval.retrieval_profile_source})`
          : ""
      }`
    : null;
  const searchMode = retrieval.search_mode ?? "vector";
  const topK =
    typeof retrieval.top_k === "number" && retrieval.top_k > 0
      ? t("summary.topK", { value: retrieval.top_k })
      : null;
  const rerank =
    retrieval.rerank_applied && retrieval.rerank_fallback_used
      ? retrieval.rerank_fallback_reason
        ? t("summary.rerankFellBackReason", {
            reason: retrieval.rerank_fallback_reason,
          })
        : t("summary.rerankFellBack")
      : retrieval.rerank_applied
        ? t("summary.rerankApplied")
        : t("summary.rerankOff");

  return joinParts([
    scope ? t("summary.scope", { scope }) : t("summary.scopeAll"),
    profile ? t("summary.profile", { profile }) : null,
    t("summary.candidates", { count: candidateCount }),
    t("summary.chunks", { count: retrieval.selected_count }),
    topK,
    t("summary.mode", { mode: searchMode }),
    rerank,
  ]);
}
