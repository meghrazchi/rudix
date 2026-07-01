"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  DEFAULT_WORKSPACE_EXPORT_SECTIONS,
  WORKSPACE_EXPORT_SECTION_LABELS,
  createWorkspaceExport,
  createWorkspaceImport,
  downloadWorkspacePortabilityArtifact,
  listWorkspacePortabilityJobs,
  type WorkspaceExportSection,
  type WorkspacePortabilityJob,
  type WorkspacePortabilityStatus,
} from "@/lib/api/workspace-portability";
import { canViewAdminUsage, formatInteger } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

function formatTimestamp(value: string | null): string {
  if (!value) return "N/A";
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString();
}

function formatBytes(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function triggerDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function statusClass(status: WorkspacePortabilityStatus): string {
  if (status === "completed" || status === "validated") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (status === "failed" || status === "validation_failed") {
    return "bg-rose-100 text-rose-800";
  }
  if (status === "expired") {
    return "bg-slate-200 text-slate-700";
  }
  return "bg-amber-100 text-amber-800";
}

function sectionLabel(section: string): string {
  return (
    WORKSPACE_EXPORT_SECTION_LABELS[section as WorkspaceExportSection] ??
    section.replace(/_/g, " ")
  );
}

function parseImportArtifact(input: string): Record<string, unknown> {
  const parsed = JSON.parse(input) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Import artifact must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function AdminWorkspacePortabilityPage() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const isAdminUser = canViewAdminUsage(state.session?.role);
  const [selectedSections, setSelectedSections] = useState<
    WorkspaceExportSection[]
  >(DEFAULT_WORKSPACE_EXPORT_SECTIONS);
  const [maxRows, setMaxRows] = useState(5000);
  const [importText, setImportText] = useState("");
  const [applyImport, setApplyImport] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const jobsQueryParams = useMemo(() => ({ limit: 25, offset: 0 }), []);
  const jobsQuery = useQuery({
    queryKey: queryKeys.admin.portabilityJobs(jobsQueryParams),
    queryFn: () => listWorkspacePortabilityJobs(jobsQueryParams),
    enabled: isAdminUser,
    refetchInterval: 10_000,
  });

  const exportMutation = useMutation({
    mutationFn: () =>
      createWorkspaceExport({
        sections: selectedSections,
        max_rows_per_section: maxRows,
      }),
    onSuccess: async () => {
      setFormError(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.portabilityJobs(jobsQueryParams),
      });
    },
    onError: (error) => setFormError(getApiErrorMessage(error)),
  });

  const importMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      createWorkspaceImport({ artifact: payload, apply: applyImport }),
    onSuccess: async () => {
      setFormError(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.portabilityJobs(jobsQueryParams),
      });
    },
    onError: (error) => setFormError(getApiErrorMessage(error)),
  });

  const downloadMutation = useMutation({
    mutationFn: (job: WorkspacePortabilityJob) =>
      downloadWorkspacePortabilityArtifact(job.job_id),
    onSuccess: (blob, job) => {
      triggerDownload(
        blob,
        job.artifact_filename ?? `rudix-portability-${job.job_id}.json`,
      );
    },
    onError: (error) => setFormError(getApiErrorMessage(error)),
  });

  function toggleSection(section: WorkspaceExportSection): void {
    setSelectedSections((current) =>
      current.includes(section)
        ? current.filter((item) => item !== section)
        : [...current, section],
    );
  }

  function handleExport(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (selectedSections.length === 0) {
      setFormError("Select at least one export section.");
      return;
    }
    exportMutation.mutate();
  }

  function handleImport(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    try {
      const artifact = parseImportArtifact(importText);
      importMutation.mutate(artifact);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Invalid JSON.");
    }
  }

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Workspace portability restricted"
          description="Only owner and admin roles can request workspace import or export jobs."
          compact={false}
        />
      </section>
    );
  }

  const jobs = jobsQuery.data?.items ?? [];

  return (
    <div className="flex-1 overflow-y-auto bg-slate-50/60">
      <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 lg:px-8">
        <header className="flex flex-col justify-between gap-4 border-b border-slate-200 pb-6 lg:flex-row lg:items-end">
          <div>
            <p className="text-xs font-bold tracking-[0.18em] text-indigo-600 uppercase">
              Workspace Portability
            </p>
            <h1 className="mt-2 text-3xl font-extrabold text-slate-950">
              Import and export data
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Request sanitized workspace exports, validate import artifacts,
              and download job outputs. Exports exclude document files,
              embeddings, API key hashes, webhook secrets, and connector
              credentials.
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm">
            <span className="font-semibold text-slate-900">
              {formatInteger(jobsQuery.data?.total ?? 0)}
            </span>{" "}
            jobs tracked
          </div>
        </header>

        {formError ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {formError}
          </div>
        ) : null}

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1fr]">
          <form
            onSubmit={handleExport}
            className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-slate-950">
                  Request export
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Choose the workspace sections to package into a JSON artifact.
                </p>
              </div>
              <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700 uppercase">
                Sanitized
              </span>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {DEFAULT_WORKSPACE_EXPORT_SECTIONS.map((section) => (
                <label
                  key={section}
                  className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:border-indigo-300"
                >
                  <input
                    type="checkbox"
                    checked={selectedSections.includes(section)}
                    onChange={() => toggleSection(section)}
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600"
                  />
                  {WORKSPACE_EXPORT_SECTION_LABELS[section]}
                </label>
              ))}
            </div>

            <label className="mt-5 block text-sm font-medium text-slate-700">
              Max rows per section
              <input
                type="number"
                min={1}
                max={10000}
                value={maxRows}
                onChange={(event) =>
                  setMaxRows(Number.parseInt(event.target.value, 10) || 1)
                }
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>

            <button
              type="submit"
              disabled={exportMutation.isPending}
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
            >
              {exportMutation.isPending
                ? "Creating export..."
                : "Create export job"}
            </button>
          </form>

          <form
            onSubmit={handleImport}
            className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
          >
            <h2 className="text-lg font-bold text-slate-950">
              Validate import
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Paste a Rudix workspace export JSON. Validation always runs before
              any records are created.
            </p>
            <textarea
              value={importText}
              onChange={(event) => setImportText(event.target.value)}
              rows={10}
              spellCheck={false}
              className="mt-5 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs text-slate-800"
              placeholder='{"schema_version":"rudix.workspace_export.v1","sections":{...}}'
            />
            <label className="mt-4 flex items-start gap-3 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={applyImport}
                onChange={(event) => setApplyImport(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600"
              />
              Apply validated records for collections, metadata fields, and
              evaluation datasets
            </label>
            <button
              type="submit"
              disabled={
                importMutation.isPending || importText.trim().length === 0
              }
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
            >
              {importMutation.isPending
                ? "Validating import..."
                : "Validate import"}
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
            <div>
              <h2 className="text-lg font-bold text-slate-950">Job status</h2>
              <p className="text-sm text-slate-500">
                Recent export and import jobs for this organization.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void jobsQuery.refetch()}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Refresh
            </button>
          </div>

          <div className="p-6">
            {jobsQuery.isLoading ? (
              <LoadingState
                title="Loading portability jobs"
                description="Fetching the latest import and export activity."
              />
            ) : jobsQuery.isError ? (
              <ErrorState
                title="Unable to load portability jobs"
                error={jobsQuery.error}
                onRetry={() => void jobsQuery.refetch()}
              />
            ) : jobs.length === 0 ? (
              <EmptyState
                title="No portability jobs yet"
                description="Create an export or validate an import to start tracking jobs here."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="text-left text-xs font-bold tracking-wide text-slate-500 uppercase">
                    <tr>
                      <th className="px-3 py-2">Type</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Sections</th>
                      <th className="px-3 py-2">Records</th>
                      <th className="px-3 py-2">Artifact</th>
                      <th className="px-3 py-2">Created</th>
                      <th className="px-3 py-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {jobs.map((job) => (
                      <tr key={job.job_id} className="align-top">
                        <td className="px-3 py-3 font-medium text-slate-900">
                          {job.job_type}
                        </td>
                        <td className="px-3 py-3">
                          <span
                            className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClass(job.status)}`}
                          >
                            {job.status.replace(/_/g, " ")}
                          </span>
                          {job.validation_errors.length > 0 ? (
                            <p className="mt-2 text-xs text-rose-700">
                              {job.validation_errors[0]?.message}
                            </p>
                          ) : null}
                          {job.warnings.length > 0 ? (
                            <p className="mt-2 text-xs text-amber-700">
                              {job.warnings[0]?.message}
                            </p>
                          ) : null}
                        </td>
                        <td className="max-w-xs px-3 py-3 text-slate-600">
                          {job.requested_sections
                            .map(sectionLabel)
                            .join(", ") || "N/A"}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          {formatInteger(job.records_processed)}
                          {job.records_failed > 0
                            ? ` / ${formatInteger(job.records_failed)} failed`
                            : ""}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          <span className="block">
                            {job.artifact_filename ?? "N/A"}
                          </span>
                          <span className="text-xs text-slate-400">
                            {formatBytes(job.artifact_size_bytes)}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          {formatTimestamp(job.created_at)}
                        </td>
                        <td className="px-3 py-3">
                          <button
                            type="button"
                            disabled={
                              !job.download_available ||
                              downloadMutation.isPending
                            }
                            onClick={() => downloadMutation.mutate(job)}
                            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
                          >
                            Download
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
