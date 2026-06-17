"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  previewCollectionRules,
  type DynamicRuleSet,
  type RuleCondition,
  type RuleField,
  type RuleLogic,
  type RuleOperator,
  type PreviewRulesDocumentItem,
} from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { LoadingState } from "@/components/states/LoadingState";

// ── Field/operator metadata ──────────────────────────────────────────────────

type FieldMeta = {
  label: string;
  operators: { value: RuleOperator; label: string }[];
  valueType: "text" | "select" | "multi-select";
  options?: { value: string; label: string }[];
};

const FIELD_META: Record<RuleField, FieldMeta> = {
  file_type: {
    label: "File type",
    operators: [
      { value: "eq", label: "is" },
      { value: "neq", label: "is not" },
      { value: "in", label: "is one of" },
      { value: "not_in", label: "is not one of" },
    ],
    valueType: "multi-select",
    options: [
      { value: "pdf", label: "PDF" },
      { value: "txt", label: "TXT" },
      { value: "docx", label: "DOCX" },
    ],
  },
  language: {
    label: "Language",
    operators: [
      { value: "eq", label: "is" },
      { value: "neq", label: "is not" },
      { value: "in", label: "is one of" },
      { value: "not_in", label: "is not one of" },
    ],
    valueType: "multi-select",
    options: [
      { value: "en", label: "English" },
      { value: "de", label: "German" },
      { value: "es", label: "Spanish" },
      { value: "fr", label: "French" },
    ],
  },
  status: {
    label: "Status",
    operators: [
      { value: "eq", label: "is" },
      { value: "neq", label: "is not" },
      { value: "in", label: "is one of" },
      { value: "not_in", label: "is not one of" },
    ],
    valueType: "multi-select",
    options: [
      { value: "indexed", label: "Indexed" },
      { value: "processing", label: "Processing" },
      { value: "uploaded", label: "Uploaded" },
      { value: "failed", label: "Failed" },
    ],
  },
  ingestion_source: {
    label: "Source",
    operators: [
      { value: "eq", label: "is" },
      { value: "neq", label: "is not" },
    ],
    valueType: "select",
    options: [
      { value: "upload", label: "Manual upload" },
      { value: "connector", label: "Connector" },
    ],
  },
  trust_status: {
    label: "Trust status",
    operators: [
      { value: "eq", label: "is" },
      { value: "neq", label: "is not" },
      { value: "in", label: "is one of" },
      { value: "not_in", label: "is not one of" },
    ],
    valueType: "multi-select",
    options: [
      { value: "current", label: "Current" },
      { value: "verified", label: "Verified" },
      { value: "draft", label: "Draft" },
      { value: "stale", label: "Stale" },
      { value: "deprecated", label: "Deprecated" },
      { value: "expired", label: "Expired" },
    ],
  },
  uploaded_by_user_id: {
    label: "Uploader (user ID)",
    operators: [
      { value: "eq", label: "is" },
      { value: "neq", label: "is not" },
    ],
    valueType: "text",
  },
  tags: {
    label: "Tags",
    operators: [
      { value: "contains", label: "contains" },
      { value: "not_contains", label: "does not contain" },
    ],
    valueType: "text",
  },
};

const ALL_FIELDS = Object.keys(FIELD_META) as RuleField[];

function defaultCondition(): RuleCondition {
  return { field: "file_type", operator: "eq", value: "pdf" };
}

function isMultiOperator(op: RuleOperator) {
  return op === "in" || op === "not_in";
}

// ── Single condition row ─────────────────────────────────────────────────────

function ConditionRow({
  condition,
  index,
  canRemove,
  onChange,
  onRemove,
}: {
  condition: RuleCondition;
  index: number;
  canRemove: boolean;
  onChange: (updated: RuleCondition) => void;
  onRemove: () => void;
}) {
  const meta = FIELD_META[condition.field];
  const isMulti = isMultiOperator(condition.operator);
  const selectedValues: string[] = isMulti
    ? Array.isArray(condition.value)
      ? (condition.value as string[])
      : []
    : [];

  function handleFieldChange(newField: RuleField) {
    const newMeta = FIELD_META[newField];
    const firstOp = newMeta.operators[0]!.value;
    const firstVal =
      newMeta.valueType === "text"
        ? ""
        : isMultiOperator(firstOp)
          ? []
          : (newMeta.options?.[0]?.value ?? "");
    onChange({ field: newField, operator: firstOp, value: firstVal });
  }

  function handleOperatorChange(newOp: RuleOperator) {
    const willBeMulti = isMultiOperator(newOp);
    const wasMulti = isMultiOperator(condition.operator);
    let newValue: string | string[] = condition.value;
    if (willBeMulti && !wasMulti) {
      newValue = typeof condition.value === "string" ? [condition.value].filter(Boolean) : [];
    } else if (!willBeMulti && wasMulti) {
      newValue = Array.isArray(condition.value) ? (condition.value[0] ?? "") : "";
    }
    onChange({ ...condition, operator: newOp, value: newValue });
  }

  function toggleMultiValue(opt: string) {
    const current = selectedValues;
    const next = current.includes(opt)
      ? current.filter((v) => v !== opt)
      : [...current, opt];
    onChange({ ...condition, value: next });
  }

  return (
    <div
      data-testid={`condition-row-${index}`}
      className="flex flex-wrap items-start gap-2 rounded-xl border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2.5"
    >
      {/* Field selector */}
      <select
        aria-label="Rule field"
        value={condition.field}
        onChange={(e) => handleFieldChange(e.target.value as RuleField)}
        className="h-8 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
      >
        {ALL_FIELDS.map((f) => (
          <option key={f} value={f}>
            {FIELD_META[f].label}
          </option>
        ))}
      </select>

      {/* Operator selector */}
      <select
        aria-label="Rule operator"
        value={condition.operator}
        onChange={(e) => handleOperatorChange(e.target.value as RuleOperator)}
        className="h-8 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
      >
        {meta.operators.map((op) => (
          <option key={op.value} value={op.value}>
            {op.label}
          </option>
        ))}
      </select>

      {/* Value input */}
      {meta.valueType === "text" ? (
        <input
          type="text"
          aria-label="Rule value"
          value={typeof condition.value === "string" ? condition.value : ""}
          onChange={(e) => onChange({ ...condition, value: e.target.value })}
          placeholder="value"
          className="h-8 flex-1 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
        />
      ) : isMulti ? (
        <div className="flex flex-wrap gap-1">
          {(meta.options ?? []).map((opt) => {
            const checked = selectedValues.includes(opt.value);
            return (
              <label
                key={opt.value}
                className={`flex cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold transition-colors ${
                  checked
                    ? "border-[#3525cd] bg-[#ece8ff] text-[#3525cd]"
                    : "border-[#e4e1ee] bg-white text-[#6a6780] hover:border-[#3525cd]/30"
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  onChange={() => toggleMultiValue(opt.value)}
                />
                {opt.label}
              </label>
            );
          })}
        </div>
      ) : (
        <select
          aria-label="Rule value"
          value={typeof condition.value === "string" ? condition.value : ""}
          onChange={(e) => onChange({ ...condition, value: e.target.value })}
          className="h-8 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
        >
          {(meta.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      )}

      {/* Remove button */}
      {canRemove ? (
        <button
          type="button"
          aria-label="Remove condition"
          onClick={onRemove}
          className="ml-auto flex h-8 w-8 items-center justify-center rounded-lg text-[#b0abc8] hover:bg-rose-50 hover:text-rose-600"
        >
          <span className="material-symbols-outlined text-[18px]">
            remove_circle_outline
          </span>
        </button>
      ) : null}
    </div>
  );
}

// ── Preview panel ────────────────────────────────────────────────────────────

function PreviewPanel({
  collectionId,
  ruleSet,
}: {
  collectionId: string;
  ruleSet: DynamicRuleSet;
}) {
  const previewMutation = useMutation({
    mutationFn: () => previewCollectionRules(collectionId, ruleSet, 20),
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
          Preview matching documents
        </span>
        <button
          type="button"
          onClick={() => previewMutation.mutate()}
          disabled={previewMutation.isPending}
          className="flex items-center gap-1 rounded-lg border border-[#d2cee6] bg-white px-3 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f0ecf9] disabled:opacity-60"
        >
          <span className="material-symbols-outlined text-[14px]">
            {previewMutation.isPending ? "hourglass_empty" : "preview"}
          </span>
          {previewMutation.isPending ? "Running…" : "Run preview"}
        </button>
      </div>

      {previewMutation.isError ? (
        <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {getApiErrorMessage(previewMutation.error)}
        </p>
      ) : null}

      {previewMutation.isSuccess ? (
        <div className="rounded-xl border border-[#e4e1ee] bg-white">
          <div className="border-b border-[#e4e1ee] px-3 py-2">
            <span className="text-xs font-semibold text-[#2a2640]">
              {previewMutation.data.total === 0
                ? "No documents match"
                : `${previewMutation.data.total.toLocaleString()} document${
                    previewMutation.data.total === 1 ? "" : "s"
                  } match${previewMutation.data.total === 1 ? "es" : ""}`}
            </span>
            {previewMutation.data.total > 20 ? (
              <span className="ml-1 text-xs text-[#6a6780]">
                (showing first 20)
              </span>
            ) : null}
          </div>
          {previewMutation.data.items.length > 0 ? (
            <ul className="max-h-44 overflow-y-auto divide-y divide-[#f0ecf9]">
              {previewMutation.data.items.map((doc: PreviewRulesDocumentItem) => (
                <li
                  key={doc.document_id}
                  className="flex items-center gap-2 px-3 py-2"
                >
                  <span className="material-symbols-outlined shrink-0 text-[16px] text-[#6a6780]">
                    {doc.file_type === "pdf"
                      ? "picture_as_pdf"
                      : doc.file_type === "docx"
                        ? "article"
                        : "description"}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-[#1b1b24]">
                    {doc.filename}
                  </span>
                  <span className="shrink-0 text-[10px] font-semibold text-[#6a6780] uppercase">
                    {doc.status}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {previewMutation.isPending ? (
        <LoadingState compact title="Matching documents…" />
      ) : null}
    </div>
  );
}

// ── DynamicRuleBuilder ───────────────────────────────────────────────────────

export type DynamicRuleBuilderProps = {
  collectionId: string | null;
  value: DynamicRuleSet;
  onChange: (next: DynamicRuleSet) => void;
};

export function DynamicRuleBuilder({
  collectionId,
  value,
  onChange,
}: DynamicRuleBuilderProps) {
  const [showPreview, setShowPreview] = useState(false);

  function setLogic(logic: RuleLogic) {
    onChange({ ...value, logic });
  }

  function addCondition() {
    onChange({
      ...value,
      conditions: [...value.conditions, defaultCondition()],
    });
  }

  function updateCondition(index: number, updated: RuleCondition) {
    const next = value.conditions.map((c, i) => (i === index ? updated : c));
    onChange({ ...value, conditions: next });
  }

  function removeCondition(index: number) {
    onChange({
      ...value,
      conditions: value.conditions.filter((_, i) => i !== index),
    });
  }

  return (
    <div className="space-y-3">
      {/* Logic toggle */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
          Match
        </span>
        <div className="flex rounded-lg border border-[#d2cee6] overflow-hidden">
          {(["and", "or"] as RuleLogic[]).map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLogic(l)}
              className={`px-3 py-1 text-xs font-bold uppercase transition-colors ${
                value.logic === l
                  ? "bg-[#3525cd] text-white"
                  : "bg-white text-[#6a6780] hover:bg-[#f0ecf9]"
              }`}
            >
              {l === "and" ? "All conditions" : "Any condition"}
            </button>
          ))}
        </div>
      </div>

      {/* Conditions */}
      <div className="space-y-2">
        {value.conditions.map((condition, i) => (
          <ConditionRow
            key={i}
            index={i}
            condition={condition}
            canRemove={value.conditions.length > 1}
            onChange={(updated) => updateCondition(i, updated)}
            onRemove={() => removeCondition(i)}
          />
        ))}
      </div>

      {/* Add condition */}
      {value.conditions.length < 20 ? (
        <button
          type="button"
          onClick={addCondition}
          className="flex items-center gap-1 text-xs font-semibold text-[#3525cd] hover:underline"
        >
          <span className="material-symbols-outlined text-[16px]">add_circle</span>
          Add condition
        </button>
      ) : null}

      {/* Preview toggle */}
      {collectionId ? (
        <div>
          <button
            type="button"
            onClick={() => setShowPreview((s) => !s)}
            className="flex items-center gap-1 text-xs font-semibold text-[#6a6780] hover:text-[#3525cd]"
          >
            <span className="material-symbols-outlined text-[16px]">
              {showPreview ? "expand_less" : "expand_more"}
            </span>
            {showPreview ? "Hide preview" : "Show document preview"}
          </button>
          {showPreview ? (
            <div className="mt-2">
              <PreviewPanel collectionId={collectionId} ruleSet={value} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function emptyRuleSet(): DynamicRuleSet {
  return { logic: "and", conditions: [defaultCondition()] };
}
