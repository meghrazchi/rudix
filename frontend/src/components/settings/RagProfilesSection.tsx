"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  Archive,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Settings2,
} from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  archiveRagProfile,
  createRagProfile,
  listRagProfileVersions,
  listRagProfiles,
  rollbackRagProfile,
  setDefaultRagProfile,
  unarchiveRagProfile,
  updateRagProfile,
  type RagProfileResponse,
} from "@/lib/api/rag-profiles";
import { queryKeys } from "@/lib/api/query";
import {
  ragProfileCreateRequestSchema,
  ragProfileUpdateRequestSchema,
  rollbackRagProfileRequestSchema,
  type RollbackRagProfileRequest,
} from "@/lib/schemas/rag-profiles";
import { useAuthSession } from "@/lib/use-auth-session";

type FeedbackState = { tone: "success" | "error"; message: string } | null;

function isAdminLike(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function feedbackClass(tone: "success" | "error"): string {
  return tone === "success"
    ? "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
    : "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
}

// ---------------------------------------------------------------------------
// Profile form (create / edit)
// ---------------------------------------------------------------------------

function ProfileForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: RagProfileResponse | null;
  onSave: (data: any) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const schema = initial
    ? ragProfileUpdateRequestSchema
    : ragProfileCreateRequestSchema;
  const form = useForm<any>({
    resolver: zodResolver(schema) as any,
    defaultValues: {
      name: initial?.name ?? "",
      description: initial?.description ?? "",
      set_as_default: initial?.is_default ?? false,
      change_note: "",
      config: {
        top_k: initial?.config?.top_k ?? 10,
        rerank_enabled: initial?.config?.rerank_enabled ?? false,
        rerank_provider: initial?.config?.rerank_provider ?? "",
        rerank_model: initial?.config?.rerank_model ?? "",
        rerank_timeout_seconds:
          initial?.config?.rerank_timeout_seconds ?? "",
        rerank_batch_size: initial?.config?.rerank_batch_size ?? "",
        rerank_input_max_candidates:
          initial?.config?.rerank_input_max_candidates ?? "",
        rerank_max_candidate_chars:
          initial?.config?.rerank_max_candidate_chars ?? "",
        rerank_fallback_behavior:
          initial?.config?.rerank_fallback_behavior ?? "original",
        confidence_threshold: initial?.config?.confidence_threshold ?? 0,
        citation_strictness: initial?.config?.citation_strictness ?? "moderate",
        model_provider: initial?.config?.model_provider ?? "",
        model_name: initial?.config?.model_name ?? "",
        safety_mode: initial?.config?.safety_mode ?? "standard",
        max_context_tokens: initial?.config?.max_context_tokens ?? "",
      },
    },
    mode: "onSubmit",
  });

  const rerankEnabled = form.watch("config.rerank_enabled");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void form.handleSubmit((values) => {
          onSave(values as any);
        })(e);
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1 md:col-span-2">
          <label
            htmlFor="rag-profile-name"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Profile Name
          </label>
          <input
            id="rag-profile-name"
            {...form.register("name")}
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
          {form.formState.errors.name ? (
            <p role="alert" className="text-xs text-rose-700">
              {String(form.formState.errors.name.message)}
            </p>
          ) : null}
        </div>

        <div className="space-y-1 md:col-span-2">
          <label
            htmlFor="rag-profile-description"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Description
          </label>
          <textarea
            id="rag-profile-description"
            rows={2}
            {...form.register("description")}
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-top-k"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Top-K
          </label>
          <input
            id="rag-top-k"
            type="number"
            min={1}
            max={100}
            {...form.register("config.top_k")}
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-confidence"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Confidence Threshold (0–1)
          </label>
          <input
            id="rag-confidence"
            type="number"
            min={0}
            max={1}
            step={0.05}
            {...form.register("config.confidence_threshold")}
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-citation-strictness"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Citation Strictness
          </label>
          <select
            id="rag-citation-strictness"
            {...form.register("config.citation_strictness")}
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          >
            <option value="strict">Strict</option>
            <option value="moderate">Moderate</option>
            <option value="lenient">Lenient</option>
          </select>
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-safety-mode"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Safety Mode
          </label>
          <select
            id="rag-safety-mode"
            {...form.register("config.safety_mode")}
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          >
            <option value="strict">Strict</option>
            <option value="standard">Standard</option>
            <option value="permissive">Permissive</option>
          </select>
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-model-provider"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Model Provider
          </label>
          <input
            id="rag-model-provider"
            {...form.register("config.model_provider")}
            placeholder="e.g. openai"
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-model-name"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Model Name
          </label>
          <input
            id="rag-model-name"
            {...form.register("config.model_name")}
            placeholder="e.g. gpt-4o"
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="flex items-center gap-3 md:col-span-2">
          <input
            id="rag-rerank-enabled"
            type="checkbox"
            {...form.register("config.rerank_enabled")}
            className="h-4 w-4 rounded border-[#c7c4d8] accent-[#3525cd]"
          />
          <label
            htmlFor="rag-rerank-enabled"
            className="text-sm font-medium text-[#1b1b24]"
          >
            Enable reranking
          </label>
        </div>

        {rerankEnabled ? (
          <div className="grid gap-4 md:col-span-2 md:grid-cols-2">
            <div className="space-y-1">
              <label
                htmlFor="rag-rerank-provider"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Rerank Provider
              </label>
              <input
                id="rag-rerank-provider"
                {...form.register("config.rerank_provider")}
                placeholder="e.g. openai"
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="rag-rerank-model"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Rerank Model
              </label>
              <input
                id="rag-rerank-model"
                {...form.register("config.rerank_model")}
                placeholder="e.g. cross-encoder/ms-marco-MiniLM-L-6-v2"
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="rag-rerank-timeout"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Timeout Seconds
              </label>
              <input
                id="rag-rerank-timeout"
                type="number"
                min={0.1}
                max={120}
                step={0.1}
                {...form.register("config.rerank_timeout_seconds")}
                placeholder="Optional"
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="rag-rerank-batch-size"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Batch Size
              </label>
              <input
                id="rag-rerank-batch-size"
                type="number"
                min={1}
                max={200}
                {...form.register("config.rerank_batch_size")}
                placeholder="Optional"
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="rag-rerank-input-max"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Input Max Candidates
              </label>
              <input
                id="rag-rerank-input-max"
                type="number"
                min={1}
                max={200}
                {...form.register("config.rerank_input_max_candidates")}
                placeholder="Optional"
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="rag-rerank-candidate-chars"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Candidate Char Limit
              </label>
              <input
                id="rag-rerank-candidate-chars"
                type="number"
                min={128}
                max={20_000}
                {...form.register("config.rerank_max_candidate_chars")}
                placeholder="Optional"
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1 md:col-span-2">
              <label
                htmlFor="rag-rerank-fallback"
                className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                Fallback Behavior
              </label>
              <select
                id="rag-rerank-fallback"
                {...form.register("config.rerank_fallback_behavior")}
                className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="original">Original ranking</option>
                <option value="disabled">Disabled</option>
              </select>
            </div>
          </div>
        ) : null}

        <div className="space-y-1 md:col-span-2">
          <label
            htmlFor="rag-prompt-template"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Prompt Template{" "}
            <span className="font-normal text-[#6a6780] normal-case">
              (optional)
            </span>
          </label>
          <textarea
            id="rag-prompt-template"
            rows={4}
            {...form.register("config.prompt_template")}
            placeholder="Leave blank to use the system default prompt."
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 font-mono text-xs text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-max-context"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Max Context Tokens
          </label>
          <input
            id="rag-max-context"
            type="number"
            min={256}
            max={128_000}
            {...form.register("config.max_context_tokens")}
            placeholder="Optional"
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="space-y-1">
          <label
            htmlFor="rag-change-note"
            className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
          >
            Change Note
          </label>
          <input
            id="rag-change-note"
            {...form.register("change_note")}
            placeholder="Optional note for version history"
            className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        <div className="flex items-center gap-3 md:col-span-2">
          <input
            id="rag-set-default"
            type="checkbox"
            {...form.register("set_as_default")}
            className="h-4 w-4 rounded border-[#c7c4d8] accent-[#3525cd]"
          />
          <label
            htmlFor="rag-set-default"
            className="text-sm font-medium text-[#1b1b24]"
          >
            Set as organization default
          </label>
        </div>
      </div>

      <div className="flex justify-end gap-3 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-[#cbc5e6] px-4 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSaving}
          className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSaving ? "Saving…" : initial ? "Save changes" : "Create profile"}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Version history panel
// ---------------------------------------------------------------------------

function VersionHistoryPanel({
  profile,
  onRollback,
  isRollingBack,
}: {
  profile: RagProfileResponse;
  onRollback: (versionNumber: number, note: string) => void;
  isRollingBack: boolean;
}) {
  const versionsQuery = useQuery({
    queryKey: queryKeys.ragProfiles.versions(profile.profile_id),
    queryFn: () => listRagProfileVersions(profile.profile_id),
    retry: false,
  });

  const rollbackForm = useForm<RollbackRagProfileRequest>({
    resolver: zodResolver(rollbackRagProfileRequestSchema),
    defaultValues: { version_number: 1, change_note: "" },
    mode: "onSubmit",
  });

  if (versionsQuery.isLoading) {
    return <LoadingState compact title="Loading version history…" />;
  }
  if (versionsQuery.isError) {
    return (
      <ErrorState
        compact
        error={versionsQuery.error}
        description={getApiErrorMessage(versionsQuery.error)}
        onRetry={() => void versionsQuery.refetch()}
      />
    );
  }
  const versions = versionsQuery.data?.items ?? [];

  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-[#1b1b24]">
        Version history — current v{profile.version}
      </p>
      {versions.length === 0 ? (
        <EmptyState
          compact
          title="No version snapshots found."
          description=""
        />
      ) : (
        <div className="space-y-2">
          {versions.map((v) => (
            <div
              key={v.version_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#ece9f8] px-3 py-3"
            >
              <div>
                <p className="text-sm font-semibold text-[#1b1b24]">
                  v{v.version_number}
                  {v.version_number === profile.version ? (
                    <span className="ml-2 rounded-full bg-[#3525cd] px-2 py-0.5 text-[10px] font-bold text-white uppercase">
                      Current
                    </span>
                  ) : null}
                </p>
                <p className="text-xs text-[#5f5a74]">
                  {new Date(v.created_at).toLocaleString()}
                  {v.change_note ? ` · ${v.change_note}` : ""}
                </p>
              </div>
              {v.version_number !== profile.version ? (
                <button
                  type="button"
                  disabled={isRollingBack}
                  onClick={() =>
                    onRollback(
                      v.version_number,
                      `Rollback to v${v.version_number}`,
                    )
                  }
                  className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw size={12} className="mr-1 inline" />
                  Rollback
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profile card
// ---------------------------------------------------------------------------

function ProfileCard({
  profile,
  isAdmin,
  onEdit,
}: {
  profile: RagProfileResponse;
  isAdmin: boolean;
  onEdit: (p: RagProfileResponse) => void;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState>(null);

  const setDefaultMutation = useMutation({
    mutationFn: () => setDefaultRagProfile(profile.profile_id),
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "Default profile updated." });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.ragProfiles.all,
      });
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const archiveMutation = useMutation({
    mutationFn: () =>
      profile.is_archived
        ? unarchiveRagProfile(profile.profile_id)
        : archiveRagProfile(profile.profile_id),
    onSuccess: async () => {
      setFeedback({
        tone: "success",
        message: profile.is_archived
          ? "Profile unarchived."
          : "Profile archived.",
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.ragProfiles.all,
      });
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const rollbackMutation = useMutation({
    mutationFn: ({
      versionNumber,
      note,
    }: {
      versionNumber: number;
      note: string;
    }) =>
      rollbackRagProfile(profile.profile_id, {
        version_number: versionNumber,
        change_note: note,
      }),
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "Profile rolled back." });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.ragProfiles.all,
      });
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  return (
    <article className="rounded-xl border border-[#e1ddea] bg-[#faf9ff] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-[#1b1b24]">
              {profile.name}
            </p>
            {profile.is_default ? (
              <span className="rounded-full bg-[#3525cd] px-2 py-0.5 text-[10px] font-bold text-white uppercase">
                Default
              </span>
            ) : null}
            {profile.is_archived ? (
              <span className="rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 uppercase">
                Archived
              </span>
            ) : null}
            <span className="text-[10px] font-semibold text-[#6a6780] uppercase">
              v{profile.version}
            </span>
          </div>
          {profile.description ? (
            <p className="mt-0.5 text-xs text-[#5f5a74]">
              {profile.description}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-[#6a6780]">
            top_k: {profile.config.top_k ?? 10} · strictness:{" "}
            {profile.config.citation_strictness ?? "moderate"} · safety:{" "}
            {profile.config.safety_mode ?? "standard"}
            {profile.config.rerank_enabled ? " · rerank on" : ""}
          </p>
        </div>

        {isAdmin ? (
          <div className="flex flex-wrap items-center gap-2">
            {!profile.is_default && !profile.is_archived ? (
              <button
                type="button"
                disabled={setDefaultMutation.isPending}
                onClick={() => void setDefaultMutation.mutateAsync()}
                className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Make default
              </button>
            ) : null}
            {!profile.is_archived ? (
              <button
                type="button"
                onClick={() => onEdit(profile)}
                className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
              >
                Edit
              </button>
            ) : null}
            {!profile.is_default ? (
              <button
                type="button"
                disabled={archiveMutation.isPending}
                onClick={() => void archiveMutation.mutateAsync()}
                className="rounded-lg border border-[#e5e3f0] px-2 py-1.5 text-xs font-semibold text-[#6a6780] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                title={profile.is_archived ? "Unarchive" : "Archive"}
              >
                <Archive size={12} />
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="rounded-lg border border-[#e5e3f0] px-2 py-1.5 text-xs font-semibold text-[#6a6780] hover:bg-[#f5f3ff]"
              title="Version history"
            >
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          </div>
        ) : null}
      </div>

      {feedback ? (
        <p className={`mt-3 ${feedbackClass(feedback.tone)}`}>
          {feedback.message}
        </p>
      ) : null}

      {expanded && isAdmin ? (
        <div className="mt-4 border-t border-[#ece9f8] pt-4">
          <VersionHistoryPanel
            profile={profile}
            onRollback={(versionNumber, note) =>
              void rollbackMutation.mutateAsync({ versionNumber, note })
            }
            isRollingBack={rollbackMutation.isPending}
          />
        </div>
      ) : null}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function RagProfilesSection() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role ?? null;
  const isAdmin = isAdminLike(role);

  const [showForm, setShowForm] = useState(false);
  const [editingProfile, setEditingProfile] =
    useState<RagProfileResponse | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState>(null);

  const profilesQuery = useQuery({
    queryKey: queryKeys.ragProfiles.list({ include_archived: includeArchived }),
    queryFn: () => listRagProfiles({ include_archived: includeArchived }),
    retry: false,
  });

  const createMutation = useMutation({
    mutationFn: (payload: any) => createRagProfile(payload),
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "RAG profile created." });
      setShowForm(false);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.ragProfiles.all,
      });
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: any;
    }) => updateRagProfile(id, payload),
    onSuccess: async () => {
      setFeedback({ tone: "success", message: "RAG profile updated." });
      setEditingProfile(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.ragProfiles.all,
      });
    },
    onError: (error) =>
      setFeedback({ tone: "error", message: getApiErrorMessage(error) }),
  });

  const handleSave = (data: any) => {
    if (editingProfile) {
      void updateMutation.mutateAsync({
        id: editingProfile.profile_id,
        payload: data as any,
      });
    } else {
      void createMutation.mutateAsync(data as any);
    }
  };

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="RAG profiles section"
    >
      <div className="mb-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Settings2 size={20} className="text-[#3525cd]" aria-hidden="true" />
          <div>
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              RAG Profiles
            </h2>
            <p className="text-sm text-[#5f5a74]">
              Configure retrieval, reranking, model, and safety settings.
              Changes are versioned and audited.
            </p>
          </div>
        </div>
        {isAdmin && !showForm && !editingProfile ? (
          <button
            type="button"
            onClick={() => {
              setShowForm(true);
              setFeedback(null);
            }}
            className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            New profile
          </button>
        ) : null}
      </div>

      {!isAdmin ? (
        <ForbiddenState
          compact
          title="RAG profiles restricted"
          description="RAG profile management is available to owner/admin roles only."
          backHref="/dashboard"
          backLabel="Back to dashboard"
        />
      ) : showForm || editingProfile ? (
        <div className="rounded-xl border border-[#e1ddea] bg-[#faf9ff] p-5">
          <p className="mb-4 text-base font-semibold text-[#1b1b24]">
            {editingProfile
              ? `Edit "${editingProfile.name}"`
              : "New RAG Profile"}
          </p>
          {feedback ? (
            <p className={`mb-3 ${feedbackClass(feedback.tone)}`}>
              {feedback.message}
            </p>
          ) : null}
          <ProfileForm
            initial={editingProfile}
            onSave={handleSave}
            onCancel={() => {
              setShowForm(false);
              setEditingProfile(null);
              setFeedback(null);
            }}
            isSaving={createMutation.isPending || updateMutation.isPending}
          />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-[#5f5a74]">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
                className="h-4 w-4 rounded border-[#c7c4d8] accent-[#3525cd]"
              />
              Show archived profiles
            </label>
          </div>

          {feedback ? (
            <p className={feedbackClass(feedback.tone)}>{feedback.message}</p>
          ) : null}

          {profilesQuery.isLoading ? (
            <LoadingState compact title="Loading RAG profiles…" />
          ) : profilesQuery.isError ? (
            <ErrorState
              compact
              error={profilesQuery.error}
              description={getApiErrorMessage(profilesQuery.error)}
              onRetry={() => void profilesQuery.refetch()}
            />
          ) : !profilesQuery.data || profilesQuery.data.items.length === 0 ? (
            <EmptyState
              compact
              title="No RAG profiles yet."
              description="Create a profile to configure retrieval and generation behavior for this organization."
            />
          ) : (
            <div className="space-y-3">
              {profilesQuery.data.items.map((profile) => (
                <ProfileCard
                  key={profile.profile_id}
                  profile={profile}
                  isAdmin={isAdmin}
                  onEdit={(p) => {
                    setEditingProfile(p);
                    setFeedback(null);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
