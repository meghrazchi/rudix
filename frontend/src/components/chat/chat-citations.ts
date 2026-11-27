import type { ChatCitationResponse } from "@/lib/api/chat";

export function getCitationScore(
  citation: ChatCitationResponse,
): number | null {
  return (
    citation.rerank_score ?? citation.similarity_score ?? citation.score ?? null
  );
}

export function citationOrdinal(index: number): string {
  return `CIT-${String(index + 1).padStart(2, "0")}`;
}

export function citationDisplayTitle(
  citation: ChatCitationResponse,
  fallback: string,
): string {
  return citation.source_title ?? citation.filename ?? fallback;
}

export function citationCopyText(
  citation: ChatCitationResponse,
  label: string,
  title: string,
): string {
  return [
    `${label}: ${title}`,
    citation.page_number ? `Page: ${citation.page_number}` : null,
    citation.text_snippet ? `Excerpt: ${citation.text_snippet}` : null,
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

export function splitSentences(value: string): string[] {
  return (
    value
      .match(/[^.!?]+[.!?]+|[^.!?]+$/g)
      ?.map((sentence) => sentence.trim()) ?? [value.trim()]
  );
}

export function splitMeaningfulCitationPhrase(value: string): {
  before: string;
  highlighted: string;
  after: string;
} {
  const normalized = value.replace(/\s+/g, " ").trim();
  const matchers = [
    /\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b/i,
    /\b\d{4}\b/,
    /\b\d+(?:\.\d+)?%?\b/,
    /"[^"]+"/,
    /'[^']+'/,
  ];

  for (const matcher of matchers) {
    const found = normalized.match(matcher);
    if (found?.index != null) {
      return {
        before: "",
        highlighted: normalized,
        after: "",
      };
    }
  }

  const words = normalized.split(" ").filter(Boolean);
  if (words.length <= 3) {
    return { before: "", highlighted: normalized, after: "" };
  }

  const highlightWordCount = Math.max(
    3,
    Math.min(6, Math.round(words.length * 0.25)),
  );
  const startIndex = Math.max(
    0,
    Math.floor((words.length - highlightWordCount) / 2),
  );
  const endIndex = startIndex + highlightWordCount;

  return {
    before: words.slice(0, startIndex).join(" "),
    highlighted: words.slice(startIndex, endIndex).join(" "),
    after: words.slice(endIndex).join(" "),
  };
}

export function buildCitationExcerptParts(
  value: string,
  compact = false,
): {
  before: string;
  highlightedPrefix: string;
  highlighted: string;
  highlightedSuffix: string;
  after: string;
} {
  const normalized = value.replace(/\s+/g, " ").trim();
  const sentences = splitSentences(normalized);
  if (sentences.length === 1) {
    const sentenceParts = splitMeaningfulCitationPhrase(sentences[0]);
    return {
      before: "",
      highlightedPrefix: sentenceParts.before,
      highlighted: sentenceParts.highlighted,
      highlightedSuffix: sentenceParts.after,
      after: "",
    };
  }

  const highlightedIndex = Math.floor(sentences.length / 2);
  const contextRadius = compact ? 1 : 1;
  const startIndex = Math.max(0, highlightedIndex - contextRadius);
  const endIndex = Math.min(
    sentences.length,
    highlightedIndex + contextRadius + 1,
  );
  const sentenceParts = splitMeaningfulCitationPhrase(
    sentences[highlightedIndex],
  );

  return {
    before: sentences.slice(startIndex, highlightedIndex).join(" "),
    highlightedPrefix: sentenceParts.before,
    highlighted: sentenceParts.highlighted,
    highlightedSuffix: sentenceParts.after,
    after: sentences.slice(highlightedIndex + 1, endIndex).join(" "),
  };
}

export function buildCitationDocumentHref(
  citation: ChatCitationResponse,
): string {
  const params = new URLSearchParams();
  if (citation.chunk_id) {
    params.set("chunk_id", citation.chunk_id);
  }
  if (citation.page_number != null) {
    params.set("page", String(citation.page_number));
  }
  params.set("back", "/chat");

  const query = params.toString();
  return `/documents/${encodeURIComponent(citation.document_id)}${
    query ? `?${query}` : ""
  }`;
}

export function getCitationSourceHref(citation: ChatCitationResponse): string {
  return (
    citation.source_deep_link ??
    citation.source_url ??
    buildCitationDocumentHref(citation)
  );
}

export function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

export function toAbsoluteBrowserHref(href: string): string {
  if (typeof window === "undefined") {
    return href;
  }
  return new URL(href, window.location.origin).toString();
}

export function conflictStatusLabel(
  status: "preferred" | "conflicting" | "neutral" | null | undefined,
): string | null {
  if (status === "preferred") {
    return "Preferred";
  }
  if (status === "conflicting") {
    return "Conflicting";
  }
  return null;
}

export function citationProviderLabel(
  citation: ChatCitationResponse,
): string | null {
  return citation.source_provider_label ?? citation.source_provider ?? null;
}

export function citationFreshnessLabel(
  citation: ChatCitationResponse,
): { label: string; className: string } | null {
  const status = citation.doc_review_status ?? null;
  if (citation.doc_expired_warning || status === "expired") {
    return {
      label: "Expired",
      className:
        "rounded-full bg-rose-100 px-2 py-1 text-[10px] font-semibold text-rose-800 uppercase",
    };
  }
  if (status === "stale") {
    return {
      label: "Stale",
      className:
        "rounded-full bg-orange-100 px-2 py-1 text-[10px] font-semibold text-orange-800 uppercase",
    };
  }
  if (status === "needs_review") {
    return {
      label: "Needs review",
      className:
        "rounded-full bg-amber-100 px-2 py-1 text-[10px] font-semibold text-amber-800 uppercase",
    };
  }
  if (status === "archived") {
    return {
      label: "Archived",
      className:
        "rounded-full bg-slate-200 px-2 py-1 text-[10px] font-semibold text-slate-700 uppercase",
    };
  }
  if (citation.doc_review_status || citation.source_trust_status) {
    return {
      label: (status ?? citation.source_trust_status ?? "Current").replaceAll(
        "_",
        " ",
      ),
      className:
        "rounded-full bg-sky-100 px-2 py-1 text-[10px] font-semibold text-sky-800 uppercase",
    };
  }
  return null;
}
