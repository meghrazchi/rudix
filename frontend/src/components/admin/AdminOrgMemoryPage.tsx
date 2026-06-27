"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  adminArchiveWorkflow,
  adminDeleteWorkflow,
  adminListWorkflows,
  type WorkflowResponse,
  type WorkflowStatus,
  type WorkflowType,
} from "@/lib/api/org-memory";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

const WORKFLOW_TYPE_LABELS: Record<WorkflowType, string> = {
  audit_evidence_pack: "Audit Evidence Pack",
  policy_comparison: "Policy Comparison",
  contract_review: "Contract Review",
  onboarding_faq: "Onboarding FAQ",
  custom: "Custom",
};

const STATUS_FILTER_OPTIONS: {
  value: WorkflowStatus | "all";
  label: string;
}[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
];

function WorkflowTypeBadge({ type }: { type: WorkflowType }) {
  const colours: Record<WorkflowType, string> = {
    audit_evidence_pack: "bg-blue-50 text-blue-700 border-blue-200",
    policy_comparison: "bg-purple-50 text-purple-700 border-purple-200",
    contract_review: "bg-amber-50 text-amber-700 border-amber-200",
    onboarding_faq: "bg-emerald-50 text-emerald-700 border-emerald-200",
    custom: "bg-gray-50 text-gray-600 border-gray-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${colours[type]}`}
    >
      {WORKFLOW_TYPE_LABELS[type]}
    </span>
  );
}

function StatusBadge({ status }: { status: WorkflowStatus }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
        Active
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-100 px-2 py-0.5 text-[11px] font-semibold text-gray-500">
      Archived
    </span>
  );
}

function WorkflowRow({
  workflow,
  onArchive,
  onDelete,
  isArchiving,
  isDeleting,
}: {
  workflow: WorkflowResponse;
  onArchive: (id: string) => void;
  onDelete: (id: string) => void;
  isArchiving: boolean;
  isDeleting: boolean;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 align-top">
        <div className="text-sm font-medium text-gray-900">{workflow.name}</div>
        {workflow.description ? (
          <div className="mt-0.5 line-clamp-2 text-[11px] text-gray-500">
            {workflow.description}
          </div>
        ) : null}
      </td>
      <td className="px-4 py-3 align-top">
        <WorkflowTypeBadge type={workflow.workflow_type} />
      </td>
      <td className="px-4 py-3 align-top">
        <StatusBadge status={workflow.status} />
      </td>
      <td className="px-4 py-3 align-top text-sm text-gray-700">
        {workflow.steps.length}
      </td>
      <td className="px-4 py-3 align-top text-sm text-gray-700">
        {workflow.use_count}
      </td>
      <td className="px-4 py-3 align-top">
        {workflow.role_scope ? (
          <div className="flex flex-wrap gap-1">
            {workflow.role_scope.map((r) => (
              <span
                key={r}
                className="inline-flex rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600"
              >
                {r}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-[11px] text-gray-400 italic">All roles</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        <div className="flex items-center gap-2">
          {workflow.status === "active" ? (
            <button
              onClick={() => onArchive(workflow.workflow_id)}
              disabled={isArchiving}
              className="text-[11px] text-amber-700 hover:text-amber-900 disabled:opacity-50"
            >
              Archive
            </button>
          ) : null}
          {confirmDelete ? (
            <span className="flex items-center gap-1">
              <button
                onClick={() => onDelete(workflow.workflow_id)}
                disabled={isDeleting}
                className="text-[11px] font-semibold text-rose-700 hover:text-rose-900 disabled:opacity-50"
              >
                Confirm delete
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="text-[11px] text-gray-500 hover:text-gray-700"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="text-[11px] text-rose-600 hover:text-rose-800"
            >
              Delete
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

export function AdminOrgMemoryPage() {
  const { state } = useAuthSession();
  const session = state.status === "authenticated" ? state.session : null;
  const role = session?.role ?? null;
  const canView = canViewAdminUsage(role);

  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | "all">(
    "all",
  );
  const [typeFilter, setTypeFilter] = useState<WorkflowType | "">("");
  const [searchQuery, setSearchQuery] = useState("");

  const queryClient = useQueryClient();

  const params = {
    ...(statusFilter !== "all" ? { status: statusFilter } : {}),
    ...(typeFilter ? { workflow_type: typeFilter } : {}),
    ...(searchQuery.trim() ? { query: searchQuery.trim() } : {}),
  };

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.admin.orgMemoryWorkflows(params),
    queryFn: () => adminListWorkflows(params),
    enabled: canView,
    staleTime: 15_000,
  });

  const archiveMutation = useMutation({
    mutationFn: adminArchiveWorkflow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "memory"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: adminDeleteWorkflow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "memory"] });
    },
  });

  if (!canView) return <ForbiddenState />;
  if (isLoading) return <LoadingState />;
  if (error) {
    if (isForbiddenError(error)) return <ForbiddenState />;
    return (
      <ErrorState
        title="Failed to load org memory workflows"
        description="Try again after reloading the page."
      />
    );
  }

  const items = data?.items ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Org Memory</h1>
        <p className="mt-1 text-sm text-gray-500">
          Review and manage saved organisation workflows and procedural memory.
          Workflows store reusable step templates — no raw document text is
          persisted.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded border border-gray-200 text-[12px]">
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value)}
              className={`px-3 py-1.5 ${
                statusFilter === opt.value
                  ? "bg-[#3525cd] font-medium text-white"
                  : "bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as WorkflowType | "")}
          className="rounded border border-gray-200 bg-white px-3 py-1.5 text-[12px] text-gray-700"
        >
          <option value="">All types</option>
          {Object.entries(WORKFLOW_TYPE_LABELS).map(([val, label]) => (
            <option key={val} value={val}>
              {label}
            </option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Search workflows…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-52 rounded border border-gray-200 px-3 py-1.5 text-[12px] text-gray-700 placeholder:text-gray-400"
        />

        {data ? (
          <span className="ml-auto text-[11px] text-gray-400">
            {data.total} workflow{data.total !== 1 ? "s" : ""}
          </span>
        ) : null}
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="No workflows match the current filters"
          description="Clear the filters or save a new workflow to make it available here."
        />
      ) : (
        <div className="overflow-x-auto rounded border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Steps</th>
                <th className="px-4 py-3">Uses</th>
                <th className="px-4 py-3">Role scope</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((wf) => (
                <WorkflowRow
                  key={wf.workflow_id}
                  workflow={wf}
                  onArchive={(id) => archiveMutation.mutate(id)}
                  onDelete={(id) => deleteMutation.mutate(id)}
                  isArchiving={
                    archiveMutation.isPending &&
                    archiveMutation.variables === wf.workflow_id
                  }
                  isDeleting={
                    deleteMutation.isPending &&
                    deleteMutation.variables === wf.workflow_id
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
