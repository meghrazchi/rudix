"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  searchVerifiedAnswers,
  type VerifiedAnswerResponse,
} from "@/lib/api/verified-answers";

type Props = {
  query: string;
  collectionId?: string | null;
};

export function SuggestedKnowledgeCard({ query, collectionId }: Props) {
  const { data } = useQuery({
    queryKey: ["verified-answers", "suggested", query, collectionId],
    queryFn: () =>
      searchVerifiedAnswers(query, {
        collection_id: collectionId ?? undefined,
        limit: 3,
      }),
    enabled: query.trim().length > 0,
    staleTime: 30_000,
  });

  const cards = data?.items ?? [];
  if (cards.length === 0) return null;

  return (
    <div className="mb-4 space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
        <span
          className="material-symbols-outlined text-[13px]"
          aria-hidden="true"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          verified
        </span>
        Verified answers
      </p>
      {cards.map((card) => (
        <SuggestedCard key={card.answer_id} card={card} />
      ))}
    </div>
  );
}

function SuggestedCard({ card }: { card: VerifiedAnswerResponse }) {
  const [expanded, setExpanded] = useState(false);

  const tags = card.tags
    ? card.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  return (
    <div
      className="rounded-lg border border-emerald-200 bg-emerald-50 p-3"
      role="region"
      aria-label={`Verified answer: ${card.title}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-0.5 rounded-full border border-emerald-300 bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800 uppercase">
            <span
              className="material-symbols-outlined text-[10px]"
              aria-hidden="true"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              check_circle
            </span>
            Verified
          </span>
          {card.is_stale && (
            <span className="rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 uppercase">
              May be outdated
            </span>
          )}
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-white px-1.5 py-0.5 text-[10px] text-emerald-700"
            >
              {tag}
            </span>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="shrink-0 text-[10px] font-medium text-emerald-700 hover:text-emerald-900"
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>

      <p className="mt-1.5 text-sm font-semibold text-gray-900">{card.title}</p>

      {expanded ? (
        <>
          <p className="mt-1 text-xs text-gray-500 italic">{card.question}</p>
          <div className="mt-2 space-y-1 text-sm text-gray-700">
            {card.answer_text.split("\n").map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
          {card.citations.length > 0 && (
            <p className="mt-2 text-[10px] text-gray-400">
              {card.citations.length} source
              {card.citations.length !== 1 ? "s" : ""}
            </p>
          )}
        </>
      ) : (
        <p className="mt-1 line-clamp-2 text-sm text-gray-600">
          {card.answer_text}
        </p>
      )}
    </div>
  );
}
