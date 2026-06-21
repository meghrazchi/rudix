"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { getApiErrorMessage } from "@/lib/api/errors";
import {
  createVerifiedAnswer,
  createVerifiedAnswerFromMessage,
  type CitationIn,
  type CreateVerifiedAnswerRequest,
} from "@/lib/api/verified-answers";

type ManualMode = {
  kind: "manual";
};

type FromMessageMode = {
  kind: "from-message";
  messageId: string;
  prefillAnswerText?: string;
  prefillCitations?: CitationIn[];
};

type Props = {
  mode: ManualMode | FromMessageMode;
  onClose: () => void;
  onCreated?: (answerId: string) => void;
  invalidateKey?: unknown[];
};

export function CreateVerifiedAnswerModal({
  mode,
  onClose,
  onCreated,
  invalidateKey,
}: Props) {
  const qc = useQueryClient();

  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [answerText, setAnswerText] = useState(
    mode.kind === "from-message" ? (mode.prefillAnswerText ?? "") : "",
  );
  const [tags, setTags] = useState("");
  const [reviewDate, setReviewDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      if (mode.kind === "from-message") {
        return createVerifiedAnswerFromMessage(mode.messageId, {
          title: title.trim(),
          question: question.trim() || undefined,
          tags: tags.trim() || undefined,
          review_date: reviewDate || undefined,
          expiry_date: expiryDate || undefined,
        });
      }

      const payload: CreateVerifiedAnswerRequest = {
        title: title.trim(),
        question: question.trim(),
        answer_text: answerText.trim(),
        tags: tags.trim() || undefined,
        review_date: reviewDate || undefined,
        expiry_date: expiryDate || undefined,
      };
      return createVerifiedAnswer(payload);
    },
    onSuccess: (result) => {
      if (invalidateKey) {
        qc.invalidateQueries({ queryKey: invalidateKey });
      }
      onCreated?.(result.answer_id);
      onClose();
    },
  });

  const canSubmit =
    title.trim().length > 0 &&
    (mode.kind === "from-message" ||
      (question.trim().length > 0 && answerText.trim().length > 0));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Create knowledge card"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-base font-semibold text-gray-900">
            {mode.kind === "from-message"
              ? "Promote to knowledge card"
              : "New knowledge card"}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-gray-400 hover:text-gray-600"
          >
            ✕
          </button>
        </div>

        <div className="space-y-4 overflow-y-auto px-6 py-5" style={{ maxHeight: "70vh" }}>
          {mode.kind === "from-message" && (
            <div className="rounded-md bg-indigo-50 p-3 text-sm text-indigo-700">
              This will create a draft knowledge card from the selected answer.
              Citations will be copied automatically.
            </div>
          )}

          <div>
            <label
              htmlFor="ka-title"
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Title <span className="text-red-500">*</span>
            </label>
            <input
              id="ka-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={512}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="Short descriptive title"
            />
          </div>

          {mode.kind !== "from-message" && (
            <div>
              <label
                htmlFor="ka-question"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Canonical question <span className="text-red-500">*</span>
              </label>
              <input
                id="ka-question"
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="What question does this card answer?"
              />
            </div>
          )}

          {mode.kind !== "from-message" && (
            <div>
              <label
                htmlFor="ka-answer"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Answer <span className="text-red-500">*</span>
              </label>
              <textarea
                id="ka-answer"
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                rows={8}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="Write the verified answer here…"
              />
            </div>
          )}

          {mode.kind === "from-message" && (
            <div>
              <label
                htmlFor="ka-question-override"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Question (optional override)
              </label>
              <input
                id="ka-question-override"
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="Leave blank to use the first 200 characters of the answer"
              />
            </div>
          )}

          <div>
            <label
              htmlFor="ka-tags"
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Tags
            </label>
            <input
              id="ka-tags"
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="Comma-separated tags"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="ka-review-date"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Review date
              </label>
              <input
                id="ka-review-date"
                type="date"
                value={reviewDate}
                onChange={(e) => setReviewDate(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label
                htmlFor="ka-expiry-date"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Expiry date
              </label>
              <input
                id="ka-expiry-date"
                type="date"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          {mutation.error && (
            <p className="text-sm text-red-600" role="alert">
              {getApiErrorMessage(mutation.error)}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-gray-200 px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!canSubmit || mutation.isPending}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Creating…" : "Create draft"}
          </button>
        </div>
      </div>
    </div>
  );
}
