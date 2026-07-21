"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  DEFAULT_WORKSPACE_EXPORT_SECTIONS,
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

function formatTimestamp(value: string | null, unavailable: string): string {
  if (!value) return unavailable;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString();
}

function formatBytes(value: number | null, unavailable: string): string {
  if (value == null || !Number.isFinite(value)) return unavailable;
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

function parseImportArtifact(
  input: string,
  objectRequiredMessage: string,
): Record<string, unknown> {
  const parsed = JSON.parse(input) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(objectRequiredMessage);
  }
  return parsed as Record<string, unknown>;
}

export function AdminWorkspacePortabilityPage() {
  const t = useTranslations("adminPortability");
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
      setFormError(t("validation.selectSection"));
      return;
    }
    exportMutation.mutate();
  }

  function handleImport(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    try {
      const artifact = parseImportArtifact(
        importText,
        t("validation.objectRequired"),
      );
      importMutation.mutate(artifact);
    } catch (error) {
      setFormError(
        error instanceof Error ? error.message : t("validation.invalidJson"),
      );
    }
  }

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.restrictedTitle")}
          description={t("access.restrictedDescription")}
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
              {t("header.eyebrow")}
            </p>
            <h1 className="mt-2 text-3xl font-extrabold text-slate-950">
              {t("header.title")}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              {t("header.description")}
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm">
            <span className="font-semibold text-slate-900">
              {formatInteger(jobsQuery.data?.total ?? 0)}
            </span>{" "}
            {t("header.jobsTracked")}
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
                  {t("export.title")}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  {t("export.description")}
                </p>
              </div>
              <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700 uppercase">
                {t("export.sanitized")}
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
                  {t(`sections.${section}`)}
                </label>
              ))}
            </div>

            <label className="mt-5 block text-sm font-medium text-slate-700">
              {t("export.maxRows")}
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
                ? t("actions.creatingExport")
                : t("actions.createExport")}
            </button>
          </form>

          <form
            onSubmit={handleImport}
            className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
          >
            <h2 className="text-lg font-bold text-slate-950">
              {t("import.title")}
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {t("import.description")}
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
              {t("import.applyRecords")}
            </label>
            <button
              type="submit"
              disabled={
                importMutation.isPending || importText.trim().length === 0
              }
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
            >
              {importMutation.isPending
                ? t("actions.validatingImport")
                : t("actions.validateImport")}
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
            <div>
              <h2 className="text-lg font-bold text-slate-950">
                {t("jobs.title")}
              </h2>
              <p className="text-sm text-slate-500">{t("jobs.description")}</p>
            </div>
            <button
              type="button"
              onClick={() => void jobsQuery.refetch()}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              {t("actions.refresh")}
            </button>
          </div>

          <div className="p-6">
            {jobsQuery.isLoading ? (
              <LoadingState
                title={t("states.loadingTitle")}
                description={t("states.loadingDescription")}
              />
            ) : jobsQuery.isError ? (
              <ErrorState
                title={t("states.errorTitle")}
                error={jobsQuery.error}
                onRetry={() => void jobsQuery.refetch()}
              />
            ) : jobs.length === 0 ? (
              <EmptyState
                title={t("states.emptyTitle")}
                description={t("states.emptyDescription")}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="text-start text-xs font-bold tracking-wide text-slate-500 uppercase">
                    <tr>
                      <th className="px-3 py-2">{t("fields.type")}</th>
                      <th className="px-3 py-2">{t("fields.status")}</th>
                      <th className="px-3 py-2">{t("fields.sections")}</th>
                      <th className="px-3 py-2">{t("fields.records")}</th>
                      <th className="px-3 py-2">{t("fields.artifact")}</th>
                      <th className="px-3 py-2">{t("fields.created")}</th>
                      <th className="px-3 py-2">{t("fields.actions")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {jobs.map((job) => (
                      <tr key={job.job_id} className="align-top">
                        <td className="px-3 py-3 font-medium text-slate-900">
                          {t(`jobTypes.${job.job_type}`)}
                        </td>
                        <td className="px-3 py-3">
                          <span
                            className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClass(job.status)}`}
                          >
                            {t(`statuses.${job.status}`)}
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
                            .map((section) =>
                              t.has(`sections.${section}`)
                                ? t(`sections.${section}`)
                                : section.replace(/_/g, " "),
                            )
                            .join(", ") || t("values.unavailable")}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          {formatInteger(job.records_processed)}
                          {job.records_failed > 0
                            ? t("jobs.failedRecords", {
                                count: formatInteger(job.records_failed),
                              })
                            : ""}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          <span className="block">
                            {job.artifact_filename ?? t("values.unavailable")}
                          </span>
                          <span className="text-xs text-slate-400">
                            {formatBytes(
                              job.artifact_size_bytes,
                              t("values.unavailable"),
                            )}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          {formatTimestamp(
                            job.created_at,
                            t("values.unavailable"),
                          )}
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
                            {t("actions.download")}
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
