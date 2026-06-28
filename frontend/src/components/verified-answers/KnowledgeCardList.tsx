"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { KnowledgeCard } from "@/components/verified-answers/KnowledgeCard";
import { NetworkErrorState } from "@/components/states/NetworkErrorState";
import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import {
  listVerifiedAnswers,
  type VerifiedAnswerStatus,
} from "@/lib/api/verified-answers";

const PAGE_SIZE = 20;

const STATUS_OPTIONS: { value: VerifiedAnswerStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "pending_review", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "published", label: "Verified" },
  { value: "deprecated", label: "Deprecated" },
  { value: "archived", label: "Archived" },
];

type Props = {
  collectionId?: string;
  defaultStatus?: VerifiedAnswerStatus;
  showStatusFilter?: boolean;
};

export function KnowledgeCardList({
  collectionId,
  defaultStatus,
  showStatusFilter = true,
}: Props) {
  const [status, setStatus] = useState<VerifiedAnswerStatus | "">(
    defaultStatus ?? "",
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [offset, setOffset] = useState(0);

  const queryKey = [
    "verified-answers",
    { status, collectionId, query: searchQuery, offset },
  ];

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () =>
      listVerifiedAnswers({
        status: status || undefined,
        collection_id: collectionId,
        query: searchQuery || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  if (error) {
    return <NetworkErrorState />;
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-3">
        <input
          type="search"
          placeholder="Search knowledge cards…"
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setOffset(0);
          }}
          className="min-w-[220px] flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          aria-label="Search knowledge cards"
        />
        {showStatusFilter && (
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as VerifiedAnswerStatus | "");
              setOffset(0);
            }}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBlock key={i} className="h-48 rounded-lg" />
          ))}
        </div>
      ) : data && data.items.length > 0 ? (
        <>
          <div className="space-y-4" role="list" aria-label="Knowledge cards">
            {data.items.map((answer) => (
              <div key={answer.answer_id} role="listitem">
                <KnowledgeCard answer={answer} queryKey={queryKey} />
              </div>
            ))}
          </div>
          {totalPages > 1 && (
            <div className="mt-6 flex items-center justify-between text-sm text-gray-500">
              <span>
                {data.total} card{data.total !== 1 ? "s" : ""}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={currentPage === 1}
                  className="rounded border border-gray-300 px-3 py-1 hover:bg-gray-50 disabled:opacity-40"
                >
                  Previous
                </button>
                <span className="px-2 py-1">
                  {currentPage} / {totalPages}
                </span>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={currentPage >= totalPages}
                  className="rounded border border-gray-300 px-3 py-1 hover:bg-gray-50 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="rounded-lg border border-dashed border-gray-300 py-16 text-center text-gray-400">
          <p className="text-sm">No knowledge cards found</p>
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="mt-2 text-xs text-indigo-600 hover:underline"
            >
              Clear search
            </button>
          )}
        </div>
      )}
    </div>
  );
}
