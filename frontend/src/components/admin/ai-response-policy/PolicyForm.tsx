"use client";

import { useState, type FormEvent } from "react";
import {
  type CitationMode,
  type NoAnswerBehavior,
  type StaleSourceBehavior,
} from "@/lib/api/ai-response-policy";
import {
  CITATION_MODE_LABELS,
  NO_ANSWER_LABELS,
  STALE_LABELS,
  type FormState,
} from "@/components/admin/ai-response-policy/policyShared";

export function PolicyForm({
  initial,
  onSubmit,
  onCancel,
  isPending,
  error,
}: {
  initial: FormState;
  onSubmit: (values: FormState) => void;
  onCancel: () => void;
  isPending: boolean;
  error: string | null;
}) {
  const [form, setForm] = useState<FormState>(initial);

  function handleChange(
    e: React.ChangeEvent<
      HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    >,
  ) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit(form);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Policy Name *
        </label>
        <input
          name="policy_name"
          value={form.policy_name}
          onChange={handleChange}
          required
          maxLength={128}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          placeholder="e.g. Enterprise Safety Policy"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Description
        </label>
        <textarea
          name="description"
          value={form.description}
          onChange={handleChange}
          rows={2}
          maxLength={1024}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          placeholder="Optional description"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Citation Mode
          </label>
          <select
            name="citation_mode"
            value={form.citation_mode}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          >
            {(["required", "recommended", "disabled"] as CitationMode[]).map(
              (m) => (
                <option key={m} value={m}>
                  {CITATION_MODE_LABELS[m]}
                </option>
              ),
            )}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Low-confidence Behavior
          </label>
          <select
            name="no_answer_behavior"
            value={form.no_answer_behavior}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          >
            {(["refuse", "warn", "allow"] as NoAnswerBehavior[]).map((b) => (
              <option key={b} value={b}>
                {NO_ANSWER_LABELS[b]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Min. Confidence Threshold (0–1)
          </label>
          <input
            name="min_confidence_threshold"
            value={form.min_confidence_threshold}
            onChange={handleChange}
            type="number"
            step="0.01"
            min="0"
            max="1"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            placeholder="e.g. 0.4 (leave blank to skip)"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Stale Source Behavior
          </label>
          <select
            name="stale_source_behavior"
            value={form.stale_source_behavior}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          >
            {(["warn", "refuse", "ignore"] as StaleSourceBehavior[]).map(
              (b) => (
                <option key={b} value={b}>
                  {STALE_LABELS[b]}
                </option>
              ),
            )}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Min. Sources Required
          </label>
          <input
            name="min_sources_required"
            value={form.min_sources_required}
            onChange={handleChange}
            type="number"
            min="0"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            placeholder="e.g. 1 (leave blank to skip)"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Disclaimer Position
          </label>
          <select
            name="disclaimer_position"
            value={form.disclaimer_position}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          >
            <option value="prepend">Before answer</option>
            <option value="append">After answer</option>
          </select>
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Blocked Topics{" "}
          <span className="font-normal text-gray-500">(comma-separated)</span>
        </label>
        <input
          name="blocked_topics"
          value={form.blocked_topics}
          onChange={handleChange}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          placeholder="e.g. politics, gambling, medical advice"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Allowed Topics{" "}
          <span className="font-normal text-gray-500">
            (comma-separated, leave blank to allow all)
          </span>
        </label>
        <input
          name="allowed_topics"
          value={form.allowed_topics}
          onChange={handleChange}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          placeholder="e.g. product support, billing"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Disclaimer Text
        </label>
        <textarea
          name="disclaimer_text"
          value={form.disclaimer_text}
          onChange={handleChange}
          rows={2}
          maxLength={2048}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          placeholder="Text shown before or after every answer"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Refusal Message
        </label>
        <textarea
          name="refusal_message"
          value={form.refusal_message}
          onChange={handleChange}
          rows={2}
          maxLength={1024}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          placeholder="Message shown when a policy rule blocks an answer"
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
