"use client";

import {
  Eye,
  FileText,
  GitBranch,
  History,
  Play,
  RotateCcw,
  Save,
  Send,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  createPromptTemplateDraft,
  getPromptTemplate,
  listPromptTemplateEvalResults,
  listPromptTemplates,
  previewPromptTemplate,
  publishPromptTemplateVersion,
  rollbackPromptTemplate,
  submitPromptTemplateVersionForReview,
  updatePromptTemplateVersion,
} from "@/lib/api/prompt-templates";
import { queryKeys } from "@/lib/api/query";
import type {
  PromptTemplate,
  PromptTemplateKey,
  PromptTemplatePreview,
  PromptTemplateVariable,
  PromptTemplateVersion,
} from "@/lib/schemas/prompt-templates";
import { promptTemplateVariableSchema } from "@/lib/schemas/prompt-templates";
import { useAuthSession } from "@/lib/use-auth-session";

type Feedback = { tone: "success" | "error"; message: string } | null;

const TEMPLATE_LABELS: Record<PromptTemplateKey, string> = {
  answer_generation: "Answer generation",
  summarization: "Summarization",
  comparison: "Comparison",
  citation_validation: "Citation validation",
  agent_planning: "Agent planning",
};

function isAdminLike(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function feedbackClass(tone: "success" | "error"): string {
  return tone === "success"
    ? "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
    : "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
}

function stateClass(state: string): string {
  if (state === "published") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (state === "review") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function parseJson<T>(value: string, label: string): T {
  try {
    return JSON.parse(value) as T;
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
}

function parseVariables(
  value: string,
  label: string,
): PromptTemplateVariable[] {
  const parsed = parseJson<unknown>(value, label);
  const result = promptTemplateVariableSchema.array().safeParse(parsed);
  if (!result.success) {
    throw new Error(`${label} must be an array of variable definitions.`);
  }
  return result.data;
}

function formatDate(value: string | null): string {
  if (!value) return "Not published";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function metricValue(summary: Record<string, unknown> | null): string {
  if (!summary) return "No summary";
  const value = summary.overall_score ?? summary.answer_relevance_score;
  if (typeof value === "number") return value.toFixed(2);
  return "Summary ready";
}

function TemplateListItem({
  template,
  selected,
  onSelect,
}: {
  template: PromptTemplate;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "w-full rounded-xl border px-4 py-3 text-left transition-colors",
        selected
          ? "border-[#3525cd] bg-[#f4f2ff]"
          : "border-[#e1ddea] bg-white hover:bg-[#faf9ff]",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[#1b1b24]">
            {TEMPLATE_LABELS[template.template_key]}
          </p>
          <p className="mt-1 line-clamp-2 text-xs text-[#5f5a74]">
            {template.description}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-[#d8d2f1] px-2 py-0.5 text-[10px] font-semibold text-[#4d3fc0] uppercase">
          v{template.active_version_number ?? "-"}
        </span>
      </div>
      <p className="mt-2 text-xs text-[#6a6780]">
        {template.eval_run_count} eval runs on active version
      </p>
    </button>
  );
}

function VersionTimeline({
  versions,
  selectedVersionNumber,
  onSelect,
  onRollback,
  isRollingBack,
}: {
  versions: PromptTemplateVersion[];
  selectedVersionNumber: number | null;
  onSelect: (versionNumber: number) => void;
  onRollback: (versionNumber: number) => void;
  isRollingBack: boolean;
}) {
  if (versions.length === 0) {
    return <EmptyState compact title="No versions found." description="" />;
  }

  return (
    <div className="space-y-2">
      {versions.map((version) => (
        <div
          key={version.version_id}
          className={[
            "rounded-xl border px-3 py-3",
            selectedVersionNumber === version.version_number
              ? "border-[#3525cd] bg-[#f7f5ff]"
              : "border-[#e6e1f2] bg-white",
          ].join(" ")}
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <button
              type="button"
              onClick={() => onSelect(version.version_number)}
              className="text-left"
            >
              <span className="text-sm font-semibold text-[#1b1b24]">
                Version {version.version_number}
              </span>
              {version.is_active ? (
                <span className="ml-2 rounded-full bg-[#3525cd] px-2 py-0.5 text-[10px] font-bold text-white uppercase">
                  Active
                </span>
              ) : null}
            </button>
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${stateClass(
                version.state,
              )}`}
            >
              {version.state}
            </span>
          </div>
          <p className="mt-1 text-xs text-[#6a6780]">
            {formatDate(version.published_at ?? version.created_at)}
            {version.change_note ? ` · ${version.change_note}` : ""}
          </p>
          {version.state === "published" && !version.is_active ? (
            <button
              type="button"
              disabled={isRollingBack}
              onClick={() => onRollback(version.version_number)}
              className="mt-2 inline-flex items-center gap-1 rounded-lg border border-[#cbc5e6] px-2.5 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RotateCcw size={12} aria-hidden="true" />
              Rollback
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function PromptTemplatesSection() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const isAdmin = isAdminLike(state.session?.role);
  const [selectedKeyOverride, setSelectedKeyOverride] =
    useState<PromptTemplateKey | null>(null);
  const [selectedVersionNumber, setSelectedVersionNumber] = useState<
    number | null
  >(null);
  const [content, setContent] = useState("");
  const [variablesJson, setVariablesJson] = useState("[]");
  const [schemaJson, setSchemaJson] = useState("{}");
  const [contextJson, setContextJson] = useState("{}");
  const [changeNote, setChangeNote] = useState("");
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [preview, setPreview] = useState<PromptTemplatePreview | null>(null);

  const templatesQuery = useQuery({
    queryKey: queryKeys.promptTemplates.list(),
    queryFn: () => listPromptTemplates(),
    enabled: isAdmin,
    retry: false,
  });
  const selectedKey =
    selectedKeyOverride ?? templatesQuery.data?.items[0]?.template_key ?? null;

  const detailQuery = useQuery({
    queryKey: selectedKey
      ? queryKeys.promptTemplates.detail(selectedKey)
      : queryKeys.promptTemplates.detail("none"),
    queryFn: () => getPromptTemplate(selectedKey as PromptTemplateKey),
    enabled: isAdmin && selectedKey !== null,
    retry: false,
  });

  const versions = useMemo(
    () => detailQuery.data?.versions.items ?? [],
    [detailQuery.data],
  );
  const selectedVersion = useMemo(
    () =>
      versions.find(
        (version) => version.version_number === selectedVersionNumber,
      ) ??
      detailQuery.data?.active_version ??
      versions[0] ??
      null,
    [detailQuery.data?.active_version, selectedVersionNumber, versions],
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!selectedVersion) return;
    setContent(selectedVersion.content);
    setVariablesJson(formatJson(selectedVersion.variables));
    setSchemaJson(formatJson(selectedVersion.variable_schema));
    setContextJson(formatJson(selectedVersion.preview_context));
    setChangeNote(selectedVersion.change_note ?? "");
    setPreview(null);
    setFeedback(null);
  }, [selectedVersion]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const evalResultsQuery = useQuery({
    queryKey:
      selectedKey && selectedVersion
        ? queryKeys.promptTemplates.evalResults(
            selectedKey,
            selectedVersion.version_number,
          )
        : queryKeys.promptTemplates.evalResults("none", 0),
    queryFn: () =>
      listPromptTemplateEvalResults(
        selectedKey as PromptTemplateKey,
        selectedVersion?.version_number ?? 1,
      ),
    enabled: isAdmin && selectedKey !== null && selectedVersion !== null,
    retry: false,
  });

  async function invalidatePromptQueries(): Promise<void> {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.promptTemplates.all,
    });
  }

  const createDraftMutation = useMutation({
    mutationFn: () =>
      createPromptTemplateDraft(selectedKey as PromptTemplateKey, {
        source_version_number: selectedVersion?.version_number ?? null,
        change_note: changeNote || null,
      }),
    onSuccess: async (version) => {
      setFeedback({ tone: "success", message: "Draft version created." });
      setSelectedVersionNumber(version.version_number);
      await invalidatePromptQueries();
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      const variables = parseVariables(variablesJson, "Variables");
      const variableSchema = parseJson<Record<string, unknown>>(
        schemaJson,
        "Variable schema",
      );
      const previewContext = parseJson<Record<string, unknown>>(
        contextJson,
        "Preview context",
      );
      return updatePromptTemplateVersion(
        selectedKey as PromptTemplateKey,
        selectedVersion?.version_number ?? 1,
        {
          content,
          variables,
          variable_schema: variableSchema,
          preview_context: previewContext,
          change_note: changeNote || null,
        },
      );
    },
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "Prompt version saved." });
      await invalidatePromptQueries();
    },
    onError: (error) =>
      setFeedback({
        tone: "error",
        message:
          error instanceof Error ? error.message : getApiErrorMessage(error),
      }),
  });

  const reviewMutation = useMutation({
    mutationFn: () =>
      submitPromptTemplateVersionForReview(
        selectedKey as PromptTemplateKey,
        selectedVersion?.version_number ?? 1,
      ),
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "Version moved to review." });
      await invalidatePromptQueries();
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const publishMutation = useMutation({
    mutationFn: () =>
      publishPromptTemplateVersion(
        selectedKey as PromptTemplateKey,
        selectedVersion?.version_number ?? 1,
        { change_note: changeNote || null },
      ),
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "Prompt version published." });
      await invalidatePromptQueries();
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const rollbackMutation = useMutation({
    mutationFn: (versionNumber: number) =>
      rollbackPromptTemplate(selectedKey as PromptTemplateKey, {
        version_number: versionNumber,
        change_note: `Rollback to version ${versionNumber}`,
      }),
    onSuccess: async (version) => {
      setFeedback({ tone: "success", message: "Prompt rolled back." });
      setSelectedVersionNumber(version.version_number);
      await invalidatePromptQueries();
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const previewMutation = useMutation({
    mutationFn: () => {
      const variables = parseVariables(variablesJson, "Variables");
      const variableSchema = parseJson<Record<string, unknown>>(
        schemaJson,
        "Variable schema",
      );
      const context = parseJson<Record<string, unknown>>(
        contextJson,
        "Preview context",
      );
      return previewPromptTemplate(selectedKey as PromptTemplateKey, {
        version_number: selectedVersion?.version_number,
        content,
        variables,
        variable_schema: variableSchema,
        context,
      });
    },
    onSuccess: (result) => {
      setPreview(result);
      setFeedback({ tone: "success", message: "Preview rendered." });
    },
    onError: (error) =>
      setFeedback({
        tone: "error",
        message:
          error instanceof Error ? error.message : getApiErrorMessage(error),
      }),
  });

  if (!isAdmin) {
    return (
      <section
        className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
        aria-label="Prompt templates section"
      >
        <ForbiddenState
          compact
          title="Prompt templates restricted"
          description="Prompt template management is available to owner/admin roles only."
          backHref="/dashboard"
          backLabel="Back to dashboard"
        />
      </section>
    );
  }

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Prompt templates section"
    >
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <FileText
            size={20}
            className="mt-1 text-[#3525cd]"
            aria-hidden="true"
          />
          <div>
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Prompt Templates
            </h2>
            <p className="max-w-3xl text-sm text-[#5f5a74]">
              Manage reviewed prompt versions for generation, summarization,
              comparison, citation validation, and agent planning.
            </p>
          </div>
        </div>
        {selectedVersion ? (
          <span
            className={`rounded-full border px-2 py-1 text-xs font-bold uppercase ${stateClass(
              selectedVersion.state,
            )}`}
          >
            {selectedVersion.state}
          </span>
        ) : null}
      </div>

      {templatesQuery.isLoading ? (
        <LoadingState compact title="Loading prompt templates..." />
      ) : templatesQuery.isError ? (
        <ErrorState
          compact
          error={templatesQuery.error}
          description={getApiErrorMessage(templatesQuery.error)}
          onRetry={() => void templatesQuery.refetch()}
        />
      ) : !templatesQuery.data || templatesQuery.data.items.length === 0 ? (
        <EmptyState
          compact
          title="No prompt templates found."
          description="Default prompt templates will be created when the backend is available."
        />
      ) : (
        <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
          <div className="space-y-3">
            {templatesQuery.data.items.map((template) => (
              <TemplateListItem
                key={template.prompt_template_id}
                template={template}
                selected={selectedKey === template.template_key}
                onSelect={() => {
                  setSelectedKeyOverride(template.template_key);
                  setSelectedVersionNumber(null);
                }}
              />
            ))}
          </div>

          <div className="space-y-4">
            {detailQuery.isLoading ? (
              <LoadingState compact title="Loading prompt detail..." />
            ) : detailQuery.isError ? (
              <ErrorState
                compact
                error={detailQuery.error}
                description={getApiErrorMessage(detailQuery.error)}
                onRetry={() => void detailQuery.refetch()}
              />
            ) : selectedVersion ? (
              <>
                <div className="rounded-xl border border-[#e1ddea] bg-[#faf9ff] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-base font-semibold text-[#1b1b24]">
                        {detailQuery.data?.template.name}
                      </p>
                      <p className="mt-1 text-sm text-[#5f5a74]">
                        {detailQuery.data?.template.description}
                      </p>
                      <p className="mt-2 text-xs text-[#6a6780]">
                        Active version: v
                        {detailQuery.data?.template.active_version_number ??
                          "-"}{" "}
                        · Selected: v{selectedVersion.version_number}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={createDraftMutation.isPending}
                        onClick={() => createDraftMutation.mutate()}
                        className="inline-flex items-center gap-2 rounded-xl border border-[#cbc5e6] px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <GitBranch size={14} aria-hidden="true" />
                        New draft
                      </button>
                      <button
                        type="button"
                        disabled={previewMutation.isPending}
                        onClick={() => previewMutation.mutate()}
                        className="inline-flex items-center gap-2 rounded-xl border border-[#cbc5e6] px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <Eye size={14} aria-hidden="true" />
                        Preview
                      </button>
                    </div>
                  </div>
                  {feedback ? (
                    <p className={`mt-3 ${feedbackClass(feedback.tone)}`}>
                      {feedback.message}
                    </p>
                  ) : null}
                </div>

                <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <label
                        htmlFor="prompt-content"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Prompt Content
                      </label>
                      <textarea
                        id="prompt-content"
                        rows={18}
                        value={content}
                        onChange={(event) => setContent(event.target.value)}
                        disabled={selectedVersion.state === "published"}
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-3 font-mono text-xs leading-5 text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 disabled:bg-slate-50 disabled:text-slate-500"
                      />
                      {selectedVersion.state === "published" ? (
                        <p className="text-xs text-[#6a6780]">
                          Published prompt versions are immutable. Create a
                          draft to make changes.
                        </p>
                      ) : null}
                    </div>

                    <div className="grid gap-4 md:grid-cols-3">
                      <div className="space-y-2">
                        <label
                          htmlFor="prompt-variables"
                          className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                        >
                          Variables
                        </label>
                        <textarea
                          id="prompt-variables"
                          rows={9}
                          value={variablesJson}
                          onChange={(event) =>
                            setVariablesJson(event.target.value)
                          }
                          disabled={selectedVersion.state === "published"}
                          className="w-full rounded-xl border border-[#c7c4d8] bg-white px-3 py-2 font-mono text-xs text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 disabled:bg-slate-50 disabled:text-slate-500"
                        />
                      </div>
                      <div className="space-y-2">
                        <label
                          htmlFor="prompt-schema"
                          className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                        >
                          Schema
                        </label>
                        <textarea
                          id="prompt-schema"
                          rows={9}
                          value={schemaJson}
                          onChange={(event) =>
                            setSchemaJson(event.target.value)
                          }
                          disabled={selectedVersion.state === "published"}
                          className="w-full rounded-xl border border-[#c7c4d8] bg-white px-3 py-2 font-mono text-xs text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10 disabled:bg-slate-50 disabled:text-slate-500"
                        />
                      </div>
                      <div className="space-y-2">
                        <label
                          htmlFor="prompt-context"
                          className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                        >
                          Fake Context
                        </label>
                        <textarea
                          id="prompt-context"
                          rows={9}
                          value={contextJson}
                          onChange={(event) =>
                            setContextJson(event.target.value)
                          }
                          className="w-full rounded-xl border border-[#c7c4d8] bg-white px-3 py-2 font-mono text-xs text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                        />
                      </div>
                    </div>

                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <div className="min-w-[220px] flex-1 space-y-1">
                        <label
                          htmlFor="prompt-change-note"
                          className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                        >
                          Change Note
                        </label>
                        <input
                          id="prompt-change-note"
                          value={changeNote}
                          onChange={(event) =>
                            setChangeNote(event.target.value)
                          }
                          className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                        />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {selectedVersion.state !== "published" ? (
                          <button
                            type="button"
                            disabled={updateMutation.isPending}
                            onClick={() => updateMutation.mutate()}
                            className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Save size={14} aria-hidden="true" />
                            Save
                          </button>
                        ) : null}
                        {selectedVersion.state === "draft" ? (
                          <button
                            type="button"
                            disabled={reviewMutation.isPending}
                            onClick={() => reviewMutation.mutate()}
                            className="inline-flex items-center gap-2 rounded-xl border border-[#cbc5e6] px-4 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Send size={14} aria-hidden="true" />
                            Submit review
                          </button>
                        ) : null}
                        {selectedVersion.state !== "published" ? (
                          <button
                            type="button"
                            disabled={publishMutation.isPending}
                            onClick={() => publishMutation.mutate()}
                            className="inline-flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Play size={14} aria-hidden="true" />
                            Publish
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {preview ? (
                      <div className="space-y-2 rounded-xl border border-[#e1ddea] bg-white p-4">
                        <p className="text-sm font-semibold text-[#1b1b24]">
                          Rendered preview
                        </p>
                        <pre className="max-h-[360px] overflow-auto rounded-lg bg-[#15141f] p-3 text-xs whitespace-pre-wrap text-white">
                          {preview.rendered_prompt}
                        </pre>
                      </div>
                    ) : null}
                  </div>

                  <aside className="space-y-4">
                    <div className="rounded-xl border border-[#e1ddea] bg-[#faf9ff] p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <History
                          size={16}
                          className="text-[#3525cd]"
                          aria-hidden="true"
                        />
                        <p className="text-sm font-semibold text-[#1b1b24]">
                          Version history
                        </p>
                      </div>
                      <VersionTimeline
                        versions={versions}
                        selectedVersionNumber={selectedVersion.version_number}
                        onSelect={setSelectedVersionNumber}
                        onRollback={(versionNumber) =>
                          rollbackMutation.mutate(versionNumber)
                        }
                        isRollingBack={rollbackMutation.isPending}
                      />
                    </div>

                    <div className="rounded-xl border border-[#e1ddea] bg-white p-4">
                      <p className="mb-3 text-sm font-semibold text-[#1b1b24]">
                        Eval impact
                      </p>
                      {evalResultsQuery.isLoading ? (
                        <LoadingState compact title="Loading eval results..." />
                      ) : evalResultsQuery.isError ? (
                        <ErrorState
                          compact
                          error={evalResultsQuery.error}
                          description={getApiErrorMessage(
                            evalResultsQuery.error,
                          )}
                          onRetry={() => void evalResultsQuery.refetch()}
                        />
                      ) : !evalResultsQuery.data ||
                        evalResultsQuery.data.items.length === 0 ? (
                        <EmptyState
                          compact
                          title="No eval runs for this version."
                          description=""
                        />
                      ) : (
                        <div className="space-y-2">
                          {evalResultsQuery.data.items.map((run) => (
                            <div
                              key={run.evaluation_run_id}
                              className="rounded-lg border border-[#ece9f8] px-3 py-2"
                            >
                              <p className="text-xs font-semibold text-[#1b1b24]">
                                {run.run_name ?? "Untitled run"}
                              </p>
                              <p className="mt-1 text-xs text-[#6a6780]">
                                {run.status} · {metricValue(run.summary)}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </aside>
                </div>
              </>
            ) : (
              <EmptyState
                compact
                title="Select a prompt template."
                description=""
              />
            )}
          </div>
        </div>
      )}
    </section>
  );
}
