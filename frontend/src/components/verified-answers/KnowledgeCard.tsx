"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { VerifiedAnswerBadge } from "@/components/verified-answers/VerifiedAnswerBadge";
import { CitationPreviewDrawer } from "@/components/chat/DocumentPreviewModal";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  archiveVerifiedAnswer,
  submitForReview,
  approveVerifiedAnswer,
  rejectVerifiedAnswer,
  publishVerifiedAnswer,
  type CitationResponse,
  type VerifiedAnswerResponse,
} from "@/lib/api/verified-answers";
import { usePermissions } from "@/lib/use-permissions";

type Props = {
  answer: VerifiedAnswerResponse;
  queryKey: unknown[];
  showActions?: boolean;
};

export function KnowledgeCard({ answer, queryKey, showActions = true }: Props) {
  const qc = useQueryClient();
  const { role } = usePermissions();
  const [rejectNote, setRejectNote] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [previewCitationSet, setPreviewCitationSet] = useState<{
    citations: CitationResponse[];
    initialIndex: number;
  } | null>(null);

  const isAdmin = role === "owner" || role === "admin";
  const isReviewer = isAdmin || role === "reviewer";
  const isWriter = isAdmin || role === "member" || role === "reviewer";

  const invalidate = () => qc.invalidateQueries({ queryKey });

  const submitMutation = useMutation({
    mutationFn: () => submitForReview(answer.answer_id),
    onSuccess: invalidate,
  });
  const approveMutation = useMutation({
    mutationFn: () => approveVerifiedAnswer(answer.answer_id),
    onSuccess: invalidate,
  });
  const rejectMutation = useMutation({
    mutationFn: (note: string) => rejectVerifiedAnswer(answer.answer_id, note),
    onSuccess: () => {
      setShowRejectForm(false);
      setRejectNote("");
      invalidate();
    },
  });
  const publishMutation = useMutation({
    mutationFn: () => publishVerifiedAnswer(answer.answer_id),
    onSuccess: invalidate,
  });
  const archiveMutation = useMutation({
    mutationFn: () => archiveVerifiedAnswer(answer.answer_id),
    onSuccess: invalidate,
  });

  const anyLoading =
    submitMutation.isPending ||
    approveMutation.isPending ||
    rejectMutation.isPending ||
    publishMutation.isPending ||
    archiveMutation.isPending;

  const mutationError =
    submitMutation.error ||
    approveMutation.error ||
    rejectMutation.error ||
    publishMutation.error ||
    archiveMutation.error;

  const tags = answer.tags
    ? answer.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  return (
    <article
      className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
      aria-label={`Knowledge card: ${answer.title}`}
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <VerifiedAnswerBadge
            status={answer.status}
            isStale={answer.is_stale}
          />
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700"
            >
              {tag}
            </span>
          ))}
        </div>
        {showActions && (
          <Link
            href={`/admin/verified-answers/${answer.answer_id}`}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            View details
          </Link>
        )}
      </div>

      <h2 className="mb-1 text-base font-semibold text-gray-900">
        {answer.title}
      </h2>

      <p className="mb-3 text-sm text-gray-500 italic">{answer.question}</p>

      <div className="prose prose-sm max-w-none text-gray-700">
        {answer.answer_text.split("\n").map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>

      {answer.citations.length > 0 && (
        <div className="mt-4 border-t border-gray-100 pt-3">
          <p className="mb-1 text-xs font-medium text-gray-500">Sources</p>
          <ol className="space-y-1 text-xs text-gray-600">
            {answer.citations.map((cit) => (
              <li key={cit.citation_id} className="flex items-start gap-1">
                <span className="mt-0.5 font-medium text-gray-400">
                  [{cit.citation_order + 1}]
                </span>
                <button
                  type="button"
                  onClick={() => {
                    const siblings = answer.citations.filter(
                      (item) => item.document_id === cit.document_id,
                    );
                    setPreviewCitationSet({
                      citations: siblings.length > 0 ? siblings : [cit],
                      initialIndex: Math.max(0, siblings.indexOf(cit)),
                    });
                  }}
                  className="text-left"
                >
                  {cit.text_snippet ? (
                    <>
                      &ldquo;{cit.text_snippet.slice(0, 120)}
                      {cit.text_snippet.length > 120 ? "…" : ""}&rdquo;
                    </>
                  ) : (
                    <span className="text-gray-400">
                      Document {cit.document_id.slice(0, 8)}…
                    </span>
                  )}
                  {cit.page_number && (
                    <span className="ml-1 text-gray-400">
                      p. {cit.page_number}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {answer.is_stale && (
        <div className="mt-3 rounded-md bg-amber-50 p-2 text-xs text-amber-700">
          ⚠ This card is past its review or expiry date and may be outdated.
        </div>
      )}

      {mutationError && (
        <p className="mt-2 text-xs text-red-600" role="alert">
          {getApiErrorMessage(mutationError)}
        </p>
      )}

      {showActions && answer.status !== "archived" && (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-gray-100 pt-3">
          {answer.status === "draft" && isWriter && (
            <button
              onClick={() => submitMutation.mutate()}
              disabled={anyLoading}
              className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Submit for review
            </button>
          )}
          {answer.status === "pending_review" && isReviewer && (
            <>
              <button
                onClick={() => approveMutation.mutate()}
                disabled={anyLoading}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => setShowRejectForm(true)}
                disabled={anyLoading}
                className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                Reject
              </button>
            </>
          )}
          {answer.status === "approved" && isAdmin && (
            <button
              onClick={() => publishMutation.mutate()}
              disabled={anyLoading}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Publish
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => {
                if (confirm("Archive this knowledge card?")) {
                  archiveMutation.mutate();
                }
              }}
              disabled={anyLoading}
              className="rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-500 hover:bg-gray-50 disabled:opacity-50"
            >
              Archive
            </button>
          )}
        </div>
      )}

      {showRejectForm && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3">
          <label
            htmlFor={`reject-note-${answer.answer_id}`}
            className="mb-1 block text-xs font-medium text-red-700"
          >
            Rejection reason (required)
          </label>
          <textarea
            id={`reject-note-${answer.answer_id}`}
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
            rows={3}
            className="w-full rounded border border-red-200 p-2 text-xs focus:ring-1 focus:ring-red-400 focus:outline-none"
          />
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => rejectMutation.mutate(rejectNote)}
              disabled={!rejectNote.trim() || rejectMutation.isPending}
              className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              Confirm rejection
            </button>
            <button
              onClick={() => setShowRejectForm(false)}
              className="rounded border border-gray-200 px-3 py-1 text-xs text-gray-500 hover:bg-white"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {previewCitationSet ? (
        <CitationPreviewDrawer
          citations={previewCitationSet.citations}
          initialIndex={previewCitationSet.initialIndex}
          onClose={() => setPreviewCitationSet(null)}
        />
      ) : null}
    </article>
  );
}
