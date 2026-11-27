"use client";

import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  previewAiResponsePolicy,
  type AiResponsePolicyResponse,
} from "@/lib/api/ai-response-policy";
import { getApiErrorMessage } from "@/lib/api/errors";
import { OutcomeChip } from "@/components/admin/ai-response-policy/policyShared";

export function PolicyPreviewPanel({
  policy,
}: {
  policy: AiResponsePolicyResponse;
}) {
  const [question, setQuestion] = useState("");
  const [confidenceScore, setConfidenceScore] = useState("0.8");
  const [citationCount, setCitationCount] = useState("1");
  const [staleCount, setStaleCount] = useState("0");
  const [error, setError] = useState<string | null>(null);

  const previewMutation = useMutation({
    mutationFn: () =>
      previewAiResponsePolicy({
        question,
        confidence_score: parseFloat(confidenceScore),
        citation_count: parseInt(citationCount, 10),
        stale_source_count: parseInt(staleCount, 10),
        policy_id: policy.policy_id,
      }),
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    previewMutation.mutate();
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Simulate how <strong>{policy.policy_name}</strong> evaluates a
        hypothetical chat scenario — no live data is affected.
      </p>
      <form onSubmit={handleSubmit} className="space-y-3">
        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Question *
          </label>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
            maxLength={1024}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            placeholder="e.g. What are the payment options?"
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Confidence (0–1)
            </label>
            <input
              value={confidenceScore}
              onChange={(e) => setConfidenceScore(e.target.value)}
              type="number"
              step="0.01"
              min="0"
              max="1"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Citations
            </label>
            <input
              value={citationCount}
              onChange={(e) => setCitationCount(e.target.value)}
              type="number"
              min="0"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Stale sources
            </label>
            <input
              value={staleCount}
              onChange={(e) => setStaleCount(e.target.value)}
              type="number"
              min="0"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={previewMutation.isPending}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {previewMutation.isPending ? "Simulating…" : "Run Preview"}
        </button>
      </form>

      {previewMutation.data && (
        <div className="mt-4 space-y-2 rounded border border-gray-200 bg-gray-50 p-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-700">Outcome:</span>
            <OutcomeChip outcome={previewMutation.data.outcome} />
            <span className="text-xs text-gray-500">
              via {previewMutation.data.policy_source}
            </span>
          </div>
          {previewMutation.data.violated_rules.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600">
                Violated rules:
              </p>
              <ul className="mt-1 space-y-0.5">
                {previewMutation.data.violated_rules.map((r) => (
                  <li key={r} className="text-xs text-red-700">
                    • {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {previewMutation.data.warning_flags.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600">Warnings:</p>
              <ul className="mt-1 space-y-0.5">
                {previewMutation.data.warning_flags.map((f) => (
                  <li key={f} className="text-xs text-yellow-700">
                    • {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {previewMutation.data.refusal_message && (
            <p className="text-xs text-gray-700">
              <span className="font-medium">Refusal message:</span>{" "}
              {previewMutation.data.refusal_message}
            </p>
          )}
          {previewMutation.data.disclaimer_text && (
            <p className="text-xs text-gray-700">
              <span className="font-medium">Disclaimer:</span>{" "}
              {previewMutation.data.disclaimer_text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
