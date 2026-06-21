"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getDocumentMetadata,
  getDocumentMetadataAudit,
  listMetadataFields,
  setDocumentMetadata,
  suggestTagValues,
  type DocumentMetadataValueResponse,
  type MetadataFieldResponse,
  type MetadataFieldType,
  type MetadataValueIn,
} from "@/lib/api/metadata";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";

type Props = {
  documentId: string;
  canEdit: boolean;
};

type FieldEditorValue =
  | { kind: "text"; value: string }
  | { kind: "select"; value: string }
  | { kind: "multi_select"; value: string[] }
  | { kind: "date"; value: string }
  | { kind: "boolean"; value: boolean }
  | { kind: "number"; value: string };

function initEditorValue(
  field: MetadataFieldResponse,
  current: DocumentMetadataValueResponse | undefined,
): FieldEditorValue {
  const ft = field.field_type;
  if (ft === "multi_select") {
    const v = current?.value;
    return { kind: "multi_select", value: Array.isArray(v) ? v : [] };
  }
  if (ft === "boolean") {
    return { kind: "boolean", value: current?.value === true };
  }
  if (ft === "select") {
    return { kind: "select", value: typeof current?.value === "string" ? current.value : "" };
  }
  if (ft === "number") {
    const v = current?.value;
    return {
      kind: "number",
      value: v !== null && v !== undefined ? String(v) : "",
    };
  }
  if (ft === "date") {
    return { kind: "date", value: typeof current?.value === "string" ? current.value : "" };
  }
  return { kind: "text", value: typeof current?.value === "string" ? current.value : "" };
}

function editorValueToApiValue(ev: FieldEditorValue): string | string[] | boolean | number | null {
  if (ev.kind === "multi_select") return ev.value;
  if (ev.kind === "boolean") return ev.value;
  if (ev.kind === "number") return ev.value === "" ? null : parseFloat(ev.value);
  if (ev.kind === "text" || ev.kind === "select" || ev.kind === "date") {
    return ev.value === "" ? null : ev.value;
  }
  return null;
}

function TagSuggestions({
  fieldId,
  prefix,
  onSelect,
}: {
  fieldId: string;
  prefix: string;
  onSelect: (v: string) => void;
}) {
  const { data } = useQuery({
    queryKey: ["metadata", "suggest", fieldId, prefix],
    queryFn: () => suggestTagValues(fieldId, prefix),
    enabled: prefix.length > 0,
    staleTime: 5_000,
  });

  const suggestions = data?.suggestions ?? [];
  if (!suggestions.length) return null;

  return (
    <div className="absolute z-10 mt-1 w-full rounded border border-[#d6d3e3] bg-white shadow-md">
      {suggestions.map((s) => (
        <button
          key={s}
          type="button"
          className="block w-full px-3 py-1.5 text-left text-sm text-[#2a2640] hover:bg-[#f5f4fa]"
          onClick={() => onSelect(s)}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

function FieldEditor({
  field,
  editorValue,
  onChange,
}: {
  field: MetadataFieldResponse;
  editorValue: FieldEditorValue;
  onChange: (v: FieldEditorValue) => void;
}) {
  const [suggestPrefix, setSuggestPrefix] = useState("");

  if (field.field_type === "boolean") {
    return (
      <label className="flex cursor-pointer items-center gap-2 text-sm text-[#2a2640]">
        <input
          type="checkbox"
          className="h-4 w-4 accent-[#3525cd]"
          checked={editorValue.kind === "boolean" ? editorValue.value : false}
          onChange={(e) => onChange({ kind: "boolean", value: e.target.checked })}
        />
        {editorValue.kind === "boolean" && editorValue.value ? "True" : "False"}
      </label>
    );
  }

  if (field.field_type === "select" && field.allowed_values) {
    return (
      <select
        className="w-full rounded border border-[#d6d3e3] px-2 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
        value={editorValue.kind === "select" ? editorValue.value : ""}
        onChange={(e) => onChange({ kind: "select", value: e.target.value })}
      >
        <option value="">— none —</option>
        {field.allowed_values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    );
  }

  if (field.field_type === "multi_select" && field.allowed_values) {
    const selected = editorValue.kind === "multi_select" ? editorValue.value : [];
    return (
      <div className="flex flex-wrap gap-1">
        {field.allowed_values.map((v) => {
          const isSelected = selected.includes(v);
          return (
            <button
              key={v}
              type="button"
              onClick={() => {
                const next = isSelected
                  ? selected.filter((s) => s !== v)
                  : [...selected, v];
                onChange({ kind: "multi_select", value: next });
              }}
              className={`rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
                isSelected
                  ? "bg-[#3525cd] text-white"
                  : "bg-[#f5f4fa] text-[#68647b] hover:bg-[#ede8fe]"
              }`}
            >
              {v}
            </button>
          );
        })}
      </div>
    );
  }

  if (field.field_type === "multi_select") {
    const [inputVal, setInputVal] = useState("");
    const selected = editorValue.kind === "multi_select" ? editorValue.value : [];
    return (
      <div className="flex flex-col gap-1">
        <div className="relative">
          <input
            className="w-full rounded border border-[#d6d3e3] px-2 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
            placeholder="Type and press Enter"
            value={inputVal}
            onChange={(e) => {
              setInputVal(e.target.value);
              setSuggestPrefix(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && inputVal.trim()) {
                e.preventDefault();
                const v = inputVal.trim();
                if (!selected.includes(v)) {
                  onChange({ kind: "multi_select", value: [...selected, v] });
                }
                setInputVal("");
                setSuggestPrefix("");
              }
            }}
          />
          <TagSuggestions
            fieldId={field.field_id}
            prefix={suggestPrefix}
            onSelect={(v) => {
              if (!selected.includes(v)) {
                onChange({ kind: "multi_select", value: [...selected, v] });
              }
              setInputVal("");
              setSuggestPrefix("");
            }}
          />
        </div>
        {selected.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {selected.map((tag) => (
              <span
                key={tag}
                className="flex items-center gap-1 rounded-full bg-[#ede8fe] px-2 py-0.5 text-xs text-[#3525cd]"
              >
                {tag}
                <button
                  type="button"
                  onClick={() =>
                    onChange({
                      kind: "multi_select",
                      value: selected.filter((s) => s !== tag),
                    })
                  }
                  className="ml-0.5 font-bold leading-none hover:text-red-500"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (field.field_type === "date") {
    return (
      <input
        type="date"
        className="w-full rounded border border-[#d6d3e3] px-2 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
        value={editorValue.kind === "date" ? editorValue.value : ""}
        onChange={(e) => onChange({ kind: "date", value: e.target.value })}
      />
    );
  }

  if (field.field_type === "number") {
    return (
      <input
        type="number"
        className="w-full rounded border border-[#d6d3e3] px-2 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
        value={editorValue.kind === "number" ? editorValue.value : ""}
        onChange={(e) => onChange({ kind: "number", value: e.target.value })}
      />
    );
  }

  // text — with optional select-style suggestions
  return (
    <div className="relative">
      <input
        type="text"
        className="w-full rounded border border-[#d6d3e3] px-2 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
        value={editorValue.kind === "text" ? editorValue.value : ""}
        onChange={(e) => {
          onChange({ kind: "text", value: e.target.value });
          setSuggestPrefix(e.target.value);
        }}
        onBlur={() => setTimeout(() => setSuggestPrefix(""), 150)}
      />
      <TagSuggestions
        fieldId={field.field_id}
        prefix={suggestPrefix}
        onSelect={(v) => {
          onChange({ kind: "text", value: v });
          setSuggestPrefix("");
        }}
      />
    </div>
  );
}

function displayValue(val: DocumentMetadataValueResponse): string {
  const v = val.value;
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "boolean") return v ? "True" : "False";
  return String(v) || "—";
}

export function DocumentMetadataPanel({ documentId, canEdit }: Props) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editorValues, setEditorValues] = useState<
    Record<string, FieldEditorValue>
  >({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showAudit, setShowAudit] = useState(false);

  const { data: fieldsData } = useQuery({
    queryKey: queryKeys.metadata.fields(),
    queryFn: () => listMetadataFields(false),
  });

  const { data: metaData, isLoading } = useQuery({
    queryKey: queryKeys.metadata.documentValues(documentId),
    queryFn: () => getDocumentMetadata(documentId),
  });

  const { data: auditData } = useQuery({
    queryKey: queryKeys.metadata.audit(documentId),
    queryFn: () => getDocumentMetadataAudit(documentId, { limit: 20 }),
    enabled: showAudit,
  });

  const saveMutation = useMutation({
    mutationFn: (values: MetadataValueIn[]) =>
      setDocumentMetadata(documentId, { values }),
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "metadata.document.set");
      setEditing(false);
      setSaveError(null);
    },
    onError: (err: unknown) => setSaveError(getApiErrorMessage(err)),
  });

  const fields = fieldsData?.items ?? [];
  const currentValues = metaData?.values ?? [];
  const valueByFieldId = Object.fromEntries(
    currentValues.map((v) => [v.field_id, v]),
  );

  function startEditing() {
    const initial: Record<string, FieldEditorValue> = {};
    for (const field of fields) {
      initial[field.field_id] = initEditorValue(field, valueByFieldId[field.field_id]);
    }
    setEditorValues(initial);
    setEditing(true);
    setSaveError(null);
  }

  function handleSave() {
    const values: MetadataValueIn[] = fields.map((field) => ({
      field_id: field.field_id,
      value: editorValueToApiValue(editorValues[field.field_id] ?? initEditorValue(field, undefined)),
    }));
    saveMutation.mutate(values);
  }

  if (!fields.length) {
    return (
      <div className="rounded-lg border border-dashed border-[#d6d3e3] p-6 text-center text-sm text-[#a09db8]">
        No metadata fields defined. An admin can create fields under{" "}
        <strong>Admin → Metadata taxonomy</strong>.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          Metadata
        </h3>
        {canEdit && !editing && (
          <button
            onClick={startEditing}
            className="rounded border border-[#d6d3e3] px-3 py-1 text-xs text-[#3525cd] hover:bg-[#ede8fe]"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="flex flex-col gap-3">
          {fields.map((field) => (
            <div key={field.field_id} className="flex flex-col gap-1">
              <label className="text-xs font-medium text-[#68647b]">
                {field.display_name}
                {field.is_required && (
                  <span className="ml-1 text-red-500">*</span>
                )}
              </label>
              <FieldEditor
                field={field}
                editorValue={
                  editorValues[field.field_id] ??
                  initEditorValue(field, valueByFieldId[field.field_id])
                }
                onChange={(v) =>
                  setEditorValues((prev) => ({ ...prev, [field.field_id]: v }))
                }
              />
              {field.description && (
                <span className="text-xs text-[#a09db8]">
                  {field.description}
                </span>
              )}
            </div>
          ))}
          {saveError && (
            <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
              {saveError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setSaveError(null);
              }}
              className="rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#68647b] hover:bg-[#f5f4fa]"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={saveMutation.isPending}
              onClick={handleSave}
              className="rounded bg-[#3525cd] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#2a1eb0] disabled:opacity-60"
            >
              {saveMutation.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          {fields.map((field) => {
            const val = valueByFieldId[field.field_id];
            return (
              <div key={field.field_id}>
                <dt className="text-xs font-medium text-[#68647b]">
                  {field.display_name}
                </dt>
                <dd className="mt-0.5 text-sm text-[#2a2640]">
                  {val ? displayValue(val) : "—"}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      <div className="border-t border-[#f0eefa] pt-2">
        <button
          type="button"
          onClick={() => setShowAudit((v) => !v)}
          className="text-xs text-[#68647b] hover:text-[#3525cd]"
        >
          {showAudit ? "Hide audit log" : "Show audit log"}
        </button>
        {showAudit && (
          <div className="mt-2 max-h-48 overflow-y-auto rounded border border-[#f0eefa] bg-[#faf9fe] p-2">
            {!auditData?.items.length ? (
              <p className="text-xs text-[#a09db8]">No audit entries yet.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[#68647b]">
                    <th className="pb-1 text-left">Field</th>
                    <th className="pb-1 text-left">Action</th>
                    <th className="pb-1 text-left">New value</th>
                    <th className="pb-1 text-left">When</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#f0eefa]">
                  {auditData.items.map((entry) => (
                    <tr key={entry.audit_id}>
                      <td className="py-1 font-mono">{entry.field_name}</td>
                      <td className="py-1">{entry.action}</td>
                      <td className="py-1 max-w-[120px] truncate">
                        {entry.new_value ?? "—"}
                      </td>
                      <td className="py-1 text-[#a09db8]">
                        {new Date(entry.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
