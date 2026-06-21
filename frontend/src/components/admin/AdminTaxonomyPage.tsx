"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import {
  createMetadataField,
  deleteMetadataField,
  listMetadataFields,
  updateMetadataField,
  type CreateMetadataFieldRequest,
  type MetadataFieldResponse,
  type MetadataFieldType,
  type UpdateMetadataFieldRequest,
} from "@/lib/api/metadata";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { usePermissions } from "@/lib/use-permissions";

const FIELD_TYPES: { value: MetadataFieldType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "select", label: "Single Select" },
  { value: "multi_select", label: "Multi Select" },
  { value: "date", label: "Date" },
  { value: "boolean", label: "Boolean" },
  { value: "number", label: "Number" },
];

const FIELD_TYPE_LABELS: Record<MetadataFieldType, string> = {
  text: "Text",
  select: "Select",
  multi_select: "Multi Select",
  date: "Date",
  boolean: "Boolean",
  number: "Number",
};

type PanelState =
  | { kind: "idle" }
  | { kind: "create" }
  | { kind: "edit"; field: MetadataFieldResponse };

const QUERY_KEY_FIELDS = queryKeys.metadata.fields();

function FieldTypeChip({ type }: { type: MetadataFieldType }) {
  return (
    <span className="rounded bg-[#ede8fe] px-2 py-0.5 text-xs font-medium text-[#3525cd]">
      {FIELD_TYPE_LABELS[type]}
    </span>
  );
}

function FieldForm({
  initial,
  onSubmit,
  onCancel,
  isPending,
  error,
}: {
  initial?: MetadataFieldResponse;
  onSubmit: (values: CreateMetadataFieldRequest) => void;
  onCancel: () => void;
  isPending: boolean;
  error: string | null;
}) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [fieldType, setFieldType] = useState<MetadataFieldType>(
    initial?.field_type ?? "text",
  );
  const [allowedValuesRaw, setAllowedValuesRaw] = useState(
    initial?.allowed_values ? initial.allowed_values.join(", ") : "",
  );
  const [isRequired, setIsRequired] = useState(initial?.is_required ?? false);
  const [isFilterable, setIsFilterable] = useState(
    initial?.is_filterable ?? true,
  );
  const [description, setDescription] = useState(initial?.description ?? "");
  const [sortOrder, setSortOrder] = useState(String(initial?.sort_order ?? 0));

  const needsAllowed =
    fieldType === "select" || fieldType === "multi_select";

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const allowed = needsAllowed
      ? allowedValuesRaw
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean)
      : undefined;
    onSubmit({
      name: name.trim(),
      display_name: displayName.trim(),
      field_type: fieldType,
      allowed_values: allowed ?? null,
      is_required: isRequired,
      is_filterable: isFilterable,
      description: description.trim() || null,
      sort_order: parseInt(sortOrder, 10) || 0,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-[#68647b]">
            Field name <span className="text-red-500">*</span>
          </label>
          <input
            required
            disabled={isEdit}
            className="rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#2a2640] placeholder-[#a09db8] focus:border-[#3525cd] focus:outline-none disabled:cursor-not-allowed disabled:bg-[#f5f4fa]"
            placeholder="e.g. department"
            pattern="^[a-z0-9_]+$"
            title="Lowercase letters, digits, and underscores only"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {!isEdit && (
            <span className="text-xs text-[#a09db8]">
              Lowercase letters, digits, underscores only. Cannot be changed
              later.
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-[#68647b]">
            Display name <span className="text-red-500">*</span>
          </label>
          <input
            required
            className="rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#2a2640] placeholder-[#a09db8] focus:border-[#3525cd] focus:outline-none"
            placeholder="e.g. Department"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-[#68647b]">
          Field type <span className="text-red-500">*</span>
        </label>
        <select
          disabled={isEdit}
          className="rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none disabled:cursor-not-allowed disabled:bg-[#f5f4fa]"
          value={fieldType}
          onChange={(e) => setFieldType(e.target.value as MetadataFieldType)}
        >
          {FIELD_TYPES.map((ft) => (
            <option key={ft.value} value={ft.value}>
              {ft.label}
            </option>
          ))}
        </select>
        {isEdit && (
          <span className="text-xs text-[#a09db8]">Field type cannot be changed after creation.</span>
        )}
      </div>

      {needsAllowed && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-[#68647b]">
            Allowed values <span className="text-red-500">*</span>
          </label>
          <input
            required
            className="rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#2a2640] placeholder-[#a09db8] focus:border-[#3525cd] focus:outline-none"
            placeholder="e.g. Engineering, Marketing, Sales"
            value={allowedValuesRaw}
            onChange={(e) => setAllowedValuesRaw(e.target.value)}
          />
          <span className="text-xs text-[#a09db8]">Comma-separated list of allowed values.</span>
        </div>
      )}

      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-[#68647b]">
          Description
        </label>
        <textarea
          rows={2}
          className="rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#2a2640] placeholder-[#a09db8] focus:border-[#3525cd] focus:outline-none"
          placeholder="Optional description for this metadata field"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div className="flex gap-6">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-[#2a2640]">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#3525cd]"
            checked={isRequired}
            onChange={(e) => setIsRequired(e.target.checked)}
          />
          Required
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-[#2a2640]">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#3525cd]"
            checked={isFilterable}
            onChange={(e) => setIsFilterable(e.target.checked)}
          />
          Filterable
        </label>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-[#68647b]">Sort order</label>
        <input
          type="number"
          min={0}
          className="w-24 rounded border border-[#d6d3e3] px-3 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
          value={sortOrder}
          onChange={(e) => setSortOrder(e.target.value)}
        />
      </div>

      {error && (
        <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-[#d6d3e3] px-4 py-1.5 text-sm text-[#68647b] hover:bg-[#f5f4fa]"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="rounded bg-[#3525cd] px-4 py-1.5 text-sm font-medium text-white hover:bg-[#2a1eb0] disabled:opacity-60"
        >
          {isPending ? "Saving…" : isEdit ? "Save changes" : "Create field"}
        </button>
      </div>
    </form>
  );
}

export function AdminTaxonomyPage() {
  const [panel, setPanel] = useState<PanelState>({ kind: "idle" });
  const [deleteTarget, setDeleteTarget] =
    useState<MetadataFieldResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  const queryClient = useQueryClient();
  const { role } = usePermissions();

  const { data, isLoading, error } = useQuery({
    queryKey: QUERY_KEY_FIELDS,
    queryFn: () => listMetadataFields(false),
  });

  const createMutation = useMutation({
    mutationFn: (req: CreateMetadataFieldRequest) => createMetadataField(req),
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "metadata.field.create");
      setPanel({ kind: "idle" });
      setFormError(null);
    },
    onError: (err: unknown) => {
      setFormError(getApiErrorMessage(err));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      fieldId,
      req,
    }: {
      fieldId: string;
      req: UpdateMetadataFieldRequest;
    }) => updateMetadataField(fieldId, req),
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "metadata.field.update");
      setPanel({ kind: "idle" });
      setFormError(null);
    },
    onError: (err: unknown) => {
      setFormError(getApiErrorMessage(err));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (fieldId: string) => deleteMetadataField(fieldId),
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "metadata.field.delete");
      setDeleteTarget(null);
    },
    onError: (err: unknown) => {
      setFormError(getApiErrorMessage(err));
    },
  });

  if (role !== "owner" && role !== "admin") return <ForbiddenState />;
  if (isLoading) return <LoadingState />;
  if (error) {
    if (isForbiddenError(error))
      return (
        <ForbiddenState requestId={extractRequestIdFromError(error) ?? undefined} />
      );
    return <ErrorState error={error} />;
  }

  const fields = data?.items ?? [];
  const displayFields = showInactive
    ? fields
    : fields.filter((f) => f.is_active);

  function handleCreate(values: CreateMetadataFieldRequest) {
    setFormError(null);
    createMutation.mutate(values);
  }

  function handleUpdate(field: MetadataFieldResponse, values: CreateMetadataFieldRequest) {
    setFormError(null);
    updateMutation.mutate({
      fieldId: field.field_id,
      req: {
        display_name: values.display_name,
        allowed_values: values.allowed_values ?? undefined,
        is_required: values.is_required,
        is_filterable: values.is_filterable,
        description: values.description,
        sort_order: values.sort_order,
      },
    });
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#2a2640]">
            Metadata taxonomy
          </h1>
          <p className="mt-1 text-sm text-[#68647b]">
            Define custom metadata fields that users can attach to documents for
            filtering, retrieval, and governance.
          </p>
        </div>
        <button
          className="rounded bg-[#3525cd] px-4 py-2 text-sm font-medium text-white hover:bg-[#2a1eb0]"
          onClick={() => {
            setFormError(null);
            setPanel({ kind: "create" });
          }}
        >
          Add field
        </button>
      </div>

      {(panel.kind === "create" || panel.kind === "edit") && (
        <div className="rounded-lg border border-[#d6d3e3] bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-[#2a2640]">
            {panel.kind === "create" ? "New metadata field" : "Edit field"}
          </h2>
          <FieldForm
            initial={panel.kind === "edit" ? panel.field : undefined}
            onSubmit={(values) => {
              if (panel.kind === "edit") {
                handleUpdate(panel.field, values);
              } else {
                handleCreate(values);
              }
            }}
            onCancel={() => {
              setPanel({ kind: "idle" });
              setFormError(null);
            }}
            isPending={createMutation.isPending || updateMutation.isPending}
            error={formError}
          />
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-sm text-[#68647b]">
          {displayFields.length} field{displayFields.length !== 1 ? "s" : ""}
        </span>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-[#68647b]">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#3525cd]"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          Show inactive
        </label>
      </div>

      {displayFields.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#d6d3e3] p-10 text-center text-sm text-[#a09db8]">
          No metadata fields defined yet. Add one to get started.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-[#d6d3e3]">
          <table className="w-full text-sm">
            <thead className="bg-[#f5f4fa]">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-[#68647b]">
                  Name
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-[#68647b]">
                  Display name
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-[#68647b]">
                  Type
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-[#68647b]">
                  Required
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-[#68647b]">
                  Filterable
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-[#68647b]">
                  Status
                </th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[#f0eefa]">
              {displayFields.map((field) => (
                <tr key={field.field_id} className="hover:bg-[#faf9fe]">
                  <td className="px-4 py-3 font-mono text-xs text-[#2a2640]">
                    {field.name}
                  </td>
                  <td className="px-4 py-3 text-[#2a2640]">
                    {field.display_name}
                  </td>
                  <td className="px-4 py-3">
                    <FieldTypeChip type={field.field_type} />
                  </td>
                  <td className="px-4 py-3 text-[#68647b]">
                    {field.is_required ? "Yes" : "No"}
                  </td>
                  <td className="px-4 py-3 text-[#68647b]">
                    {field.is_filterable ? "Yes" : "No"}
                  </td>
                  <td className="px-4 py-3">
                    {field.is_active ? (
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
                        Active
                      </span>
                    ) : (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        className="rounded px-2 py-1 text-xs text-[#3525cd] hover:bg-[#ede8fe]"
                        onClick={() => {
                          setFormError(null);
                          setPanel({ kind: "edit", field });
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                        onClick={() => setDeleteTarget(field)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-lg">
            <h2 className="mb-2 text-base font-semibold text-[#2a2640]">
              Delete field?
            </h2>
            <p className="mb-4 text-sm text-[#68647b]">
              This will permanently delete the{" "}
              <strong>{deleteTarget.display_name}</strong> field and all
              associated document values. This cannot be undone.
            </p>
            {formError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
                {formError}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setDeleteTarget(null);
                  setFormError(null);
                }}
                className="rounded border border-[#d6d3e3] px-4 py-1.5 text-sm text-[#68647b] hover:bg-[#f5f4fa]"
              >
                Cancel
              </button>
              <button
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(deleteTarget.field_id)}
                className="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
