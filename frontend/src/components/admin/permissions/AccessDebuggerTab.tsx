"use client";

import { useId, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  explainDecision,
  type ExplainDecisionResponse,
  type TraceStep,
} from "@/lib/api/conflicts";

// ── Access debugger tab ───────────────────────────────────────────────────────

export const RESOURCE_TYPES_FOR_EXPLAIN = [
  "document",
  "collection",
  "connector",
  "connector_source_item",
  "citation",
  "graph_entity",
  "graph_evidence",
  "evaluation",
  "saved_answer",
  "knowledge_card",
  "api_key",
];

export const ACTIONS_FOR_EXPLAIN = [
  "list",
  "view",
  "search",
  "chat",
  "cite",
  "create",
  "manage",
  "sync",
  "export",
  "evaluate",
  "delete",
];

export function TraceStepRow({ step }: { step: TraceStep }) {
  const t = useTranslations("adminPermissions");
  const dotCls =
    step.outcome === "allow"
      ? "bg-emerald-400"
      : step.outcome === "deny"
        ? "bg-red-400"
        : "bg-slate-300";
  return (
    <div className="flex items-start gap-3 py-1.5">
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotCls}`} />
      <div className="flex-1 text-xs">
        <span className="font-mono text-[#2a2640]">{step.rule}</span>
        <span
          className={`ml-2 font-bold uppercase ${
            step.outcome === "allow"
              ? "text-emerald-600"
              : step.outcome === "deny"
                ? "text-red-600"
                : "text-slate-400"
          }`}
        >
          {t(`outcomes.${step.outcome}`)}
        </span>
        {step.detail && (
          <span className="ml-2 text-[#68647b]">({step.detail})</span>
        )}
      </div>
    </div>
  );
}

export function AccessDebuggerTab() {
  const t = useTranslations("adminPermissions");
  const [subjectUserId, setSubjectUserId] = useState("");
  const [resourceType, setResourceType] = useState("document");
  const [action, setAction] = useState("view");
  const [resourceId, setResourceId] = useState("");
  const [result, setResult] = useState<ExplainDecisionResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const fieldId = useId();

  const debugMutation = useMutation({
    mutationFn: () =>
      explainDecision({
        subject_user_id: subjectUserId.trim(),
        resource_type: resourceType,
        action,
        resource_id: resourceId.trim() || null,
      }),
    onSuccess: (data) => {
      setResult(data);
      setFormError(null);
    },
    onError: (err) => {
      setFormError(getApiErrorMessage(err));
      setResult(null);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!subjectUserId.trim()) {
      setFormError(t("debugger.subjectRequired"));
      return;
    }
    debugMutation.mutate();
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-[#68647b]">{t("debugger.description")}</p>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
      >
        <h3 className="text-sm font-semibold text-[#2a2640]">
          {t("debugger.checkAccess")}
        </h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label
              htmlFor={`${fieldId}-subject`}
              className="mb-1 block text-xs font-medium text-[#2a2640]"
            >
              {t("debugger.subjectUserId")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <input
              id={`${fieldId}-subject`}
              type="text"
              value={subjectUserId}
              onChange={(e) => setSubjectUserId(e.target.value)}
              required
              placeholder={t("debugger.subjectPlaceholder")}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 font-mono text-sm focus:border-[#3525cd] focus:outline-none"
            />
          </div>
          <div>
            <label
              htmlFor={`${fieldId}-resource-type`}
              className="mb-1 block text-xs font-medium text-[#2a2640]"
            >
              {t("columns.resourceType")}
            </label>
            <select
              id={`${fieldId}-resource-type`}
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
            >
              {RESOURCE_TYPES_FOR_EXPLAIN.map((rt) => (
                <option key={rt} value={rt}>
                  {rt}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor={`${fieldId}-action`}
              className="mb-1 block text-xs font-medium text-[#2a2640]"
            >
              {t("columns.action")}
            </label>
            <select
              id={`${fieldId}-action`}
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
            >
              {ACTIONS_FOR_EXPLAIN.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label
              htmlFor={`${fieldId}-resource-id`}
              className="mb-1 block text-xs font-medium text-[#2a2640]"
            >
              {t("columns.resourceId")}{" "}
              <span className="text-[#68647b]">{t("optional")}</span>
            </label>
            <input
              id={`${fieldId}-resource-id`}
              type="text"
              value={resourceId}
              onChange={(e) => setResourceId(e.target.value)}
              placeholder={t("debugger.resourcePlaceholder")}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 font-mono text-sm focus:border-[#3525cd] focus:outline-none"
            />
          </div>
        </div>

        {formError && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {formError}
          </p>
        )}

        <button
          type="submit"
          disabled={debugMutation.isPending}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
        >
          {debugMutation.isPending
            ? t("debugger.checking")
            : t("debugger.checkAccess")}
        </button>
      </form>

      {result && (
        <div className="space-y-5 rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="flex items-center gap-4">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-bold uppercase ${
                result.decision === "allow"
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-red-50 text-red-700"
              }`}
            >
              {result.decision === "allow" ? "✓" : "✗"} {result.decision}
            </span>
            <div className="text-xs text-[#68647b]">
              {t("debugger.rule")}:{" "}
              <span className="font-mono text-[#2a2640]">
                {result.matched_rule}
              </span>
              {result.deny_reason && (
                <span className="ml-3">
                  {t("columns.reason")}:{" "}
                  <span className="font-mono text-red-700">
                    {result.deny_reason}
                  </span>
                </span>
              )}
            </div>
          </div>

          <div>
            <p className="mb-2 text-xs font-bold text-[#5d58a8] uppercase">
              {t("debugger.policyTrace")}
            </p>
            <div className="divide-y divide-[#ede9fb] rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-4 py-3">
              {result.trace.map((step, i) => (
                <TraceStepRow key={i} step={step} />
              ))}
            </div>
          </div>

          {result.remediation.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-bold text-[#5d58a8] uppercase">
                {t("debugger.howToGrant")}
              </p>
              <ul className="space-y-1.5">
                {result.remediation.map((r, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-sm text-[#2a2640]"
                  >
                    <span className="mt-0.5 shrink-0 text-[#3525cd]">→</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-[#a09dbf]">
            {t("debugger.requestId")}: {result.request_id}
          </p>
        </div>
      )}
    </div>
  );
}
