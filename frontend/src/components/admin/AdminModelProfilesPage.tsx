"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteModelProfile,
  getEffectiveModelPolicy,
  listModelProfiles,
  upsertModelProfile,
  validateModelProfile,
  type ModelProfileResponse,
  type ProfileValidationIssue,
  type ResolvedTaskProfile,
  type TaskType,
  type UpsertModelProfileRequest,
} from "@/lib/api/model-profiles";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

const ALL_TASK_TYPES: TaskType[] = [
  "chat",
  "summarization",
  "comparison",
  "embeddings",
  "evaluations",
  "agentic",
];

const TASK_LABELS: Record<TaskType, string> = {
  chat: "Chat",
  summarization: "Summarization",
  comparison: "Comparison",
  embeddings: "Embeddings",
  evaluations: "Evaluations",
  agentic: "Agentic Workflows",
};

type DraftProfile = {
  profile_name: string;
  provider_type: string;
  base_model: string;
  max_tokens: string;
  temperature: string;
  json_mode: boolean;
  streaming: boolean;
  fallback_provider_key: string;
  is_experimental: boolean;
  change_note: string;
};

const EMPTY_DRAFT: DraftProfile = {
  profile_name: "",
  provider_type: "openai",
  base_model: "",
  max_tokens: "",
  temperature: "",
  json_mode: false,
  streaming: true,
  fallback_provider_key: "",
  is_experimental: false,
  change_note: "",
};

function profileToDraft(profile: ModelProfileResponse): DraftProfile {
  return {
    profile_name: profile.profile_name,
    provider_type: profile.provider_type,
    base_model: profile.base_model,
    max_tokens: profile.max_tokens?.toString() ?? "",
    temperature: profile.temperature?.toString() ?? "",
    json_mode: profile.json_mode,
    streaming: profile.streaming,
    fallback_provider_key: profile.fallback_provider_key ?? "",
    is_experimental: profile.is_experimental,
    change_note: "",
  };
}

function parseOptionalFloat(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseFloat(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseOptionalInt(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function SourceBadge({ source }: { source: ResolvedTaskProfile["source"] }) {
  const classes =
    source === "org_profile"
      ? "bg-blue-100 text-blue-800"
      : "bg-gray-100 text-gray-600";
  const label = source === "org_profile" ? "org override" : "env default";
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${classes}`}
    >
      {label}
    </span>
  );
}

function ValidationIssueList({ issues }: { issues: ProfileValidationIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1 text-sm text-red-600">
      {issues.map((issue) => (
        <li key={issue.code}>{issue.message}</li>
      ))}
    </ul>
  );
}

type ProfileEditorProps = {
  taskType: TaskType;
  existing: ModelProfileResponse | undefined;
  onSave: (taskType: TaskType, payload: UpsertModelProfileRequest) => void;
  onDelete: (taskType: TaskType) => void;
  isSaving: boolean;
  isDeleting: boolean;
  saveError: string | null;
};

function ProfileEditor({
  taskType,
  existing,
  onSave,
  onDelete,
  isSaving,
  isDeleting,
  saveError,
}: ProfileEditorProps) {
  const [draft, setDraft] = useState<DraftProfile | null>(null);
  const [validationIssues, setValidationIssues] = useState<
    ProfileValidationIssue[]
  >([]);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const activeDraft =
    draft ?? (existing ? profileToDraft(existing) : EMPTY_DRAFT);

  function update(field: keyof DraftProfile, value: string | boolean) {
    setDraft({ ...activeDraft, [field]: value });
    setValidationIssues([]);
  }

  async function handleSave() {
    const result = await validateModelProfile({
      task_type: taskType,
      provider_type: activeDraft.provider_type,
      base_model: activeDraft.base_model,
      json_mode: activeDraft.json_mode,
      is_experimental: activeDraft.is_experimental,
      fallback_provider_key: activeDraft.fallback_provider_key || null,
    });
    if (!result.valid) {
      setValidationIssues(result.issues);
      return;
    }
    onSave(taskType, {
      profile_name: activeDraft.profile_name || TASK_LABELS[taskType],
      provider_type: activeDraft.provider_type,
      base_model: activeDraft.base_model,
      max_tokens: parseOptionalInt(activeDraft.max_tokens),
      temperature: parseOptionalFloat(activeDraft.temperature),
      json_mode: activeDraft.json_mode,
      streaming: activeDraft.streaming,
      fallback_provider_key: activeDraft.fallback_provider_key || null,
      is_experimental: activeDraft.is_experimental,
      change_note: activeDraft.change_note || null,
    });
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Profile name
          </label>
          <input
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={activeDraft.profile_name}
            placeholder={TASK_LABELS[taskType]}
            onChange={(e) => update("profile_name", e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Provider type
          </label>
          <input
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={activeDraft.provider_type}
            placeholder="openai"
            onChange={(e) => update("provider_type", e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Base model
          </label>
          <input
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={activeDraft.base_model}
            placeholder={
              taskType === "embeddings" ? "text-embedding-3-small" : "gpt-4o"
            }
            onChange={(e) => update("base_model", e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Fallback provider key
          </label>
          <input
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={activeDraft.fallback_provider_key}
            placeholder="openai (optional)"
            onChange={(e) => update("fallback_provider_key", e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Max tokens
          </label>
          <input
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            type="number"
            min={1}
            value={activeDraft.max_tokens}
            placeholder="default"
            onChange={(e) => update("max_tokens", e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Temperature
          </label>
          <input
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={activeDraft.temperature}
            placeholder="default"
            onChange={(e) => update("temperature", e.target.value)}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={activeDraft.json_mode}
            onChange={(e) => update("json_mode", e.target.checked)}
          />
          JSON mode
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={activeDraft.streaming}
            onChange={(e) => update("streaming", e.target.checked)}
          />
          Streaming
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={activeDraft.is_experimental}
            onChange={(e) => update("is_experimental", e.target.checked)}
          />
          Experimental
        </label>
      </div>

      <div className="mt-3">
        <label className="mb-1 block text-xs font-medium text-gray-600">
          Change note (optional)
        </label>
        <input
          className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={activeDraft.change_note}
          placeholder="Describe this change"
          onChange={(e) => update("change_note", e.target.value)}
        />
      </div>

      {validationIssues.length > 0 && (
        <ValidationIssueList issues={validationIssues} />
      )}
      {saveError && <p className="mt-2 text-sm text-red-600">{saveError}</p>}

      <div className="mt-3 flex items-center gap-2">
        <button
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          onClick={handleSave}
          disabled={isSaving || !activeDraft.base_model.trim()}
        >
          {isSaving
            ? "Saving…"
            : existing
              ? "Update profile"
              : "Create profile"}
        </button>
        {existing && !showDeleteConfirm && (
          <button
            className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={isDeleting}
          >
            Remove override
          </button>
        )}
        {showDeleteConfirm && (
          <>
            <span className="text-sm text-gray-600">
              Revert to env default?
            </span>
            <button
              className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              onClick={() => {
                setShowDeleteConfirm(false);
                onDelete(taskType);
              }}
              disabled={isDeleting}
            >
              {isDeleting ? "Removing…" : "Confirm"}
            </button>
            <button
              className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
              onClick={() => setShowDeleteConfirm(false)}
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export function AdminModelProfilesPage() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const [savingTask, setSavingTask] = useState<TaskType | null>(null);
  const [deletingTask, setDeletingTask] = useState<TaskType | null>(null);
  const [mutationErrors, setMutationErrors] = useState<
    Partial<Record<TaskType, string>>
  >({});

  const listQuery = useQuery({
    queryKey: queryKeys.modelProfiles.list,
    queryFn: () => listModelProfiles(),
    enabled: isAdminUser,
  });

  const effectiveQuery = useQuery({
    queryKey: queryKeys.modelProfiles.effective,
    queryFn: () => getEffectiveModelPolicy(),
    enabled: isAdminUser,
  });

  const upsertMutation = useMutation({
    mutationFn: ({
      taskType,
      payload,
    }: {
      taskType: TaskType;
      payload: UpsertModelProfileRequest;
    }) => upsertModelProfile(taskType, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelProfiles.all });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (taskType: TaskType) => deleteModelProfile(taskType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelProfiles.all });
    },
  });

  async function handleSave(
    taskType: TaskType,
    payload: UpsertModelProfileRequest,
  ) {
    setSavingTask(taskType);
    setMutationErrors((prev) => ({ ...prev, [taskType]: undefined }));
    try {
      await upsertMutation.mutateAsync({ taskType, payload });
    } catch (err) {
      setMutationErrors((prev) => ({
        ...prev,
        [taskType]: getApiErrorMessage(err),
      }));
    } finally {
      setSavingTask(null);
    }
  }

  async function handleDelete(taskType: TaskType) {
    setDeletingTask(taskType);
    setMutationErrors((prev) => ({ ...prev, [taskType]: undefined }));
    try {
      await deleteMutation.mutateAsync(taskType);
    } catch (err) {
      setMutationErrors((prev) => ({
        ...prev,
        [taskType]: getApiErrorMessage(err),
      }));
    } finally {
      setDeletingTask(null);
    }
  }

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Model profiles restricted"
          description="Only owner and admin roles can manage model profiles."
          compact={false}
        />
      </section>
    );
  }

  const forbiddenError =
    effectiveQuery.isError &&
    isForbiddenError(effectiveQuery.error) &&
    effectiveQuery.error;

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Model profiles unavailable"
          description="Your role no longer has access to model profiles."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  if (effectiveQuery.isLoading) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <LoadingState
          title="Loading model profiles"
          description="Preparing organization model profile configuration."
          compact={false}
        />
      </section>
    );
  }

  if (effectiveQuery.isError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title="Unable to load model profiles"
          description={getApiErrorMessage(effectiveQuery.error)}
          compact={false}
          requestId={extractRequestIdFromError(effectiveQuery.error)}
          onRetry={() => effectiveQuery.refetch()}
        />
      </section>
    );
  }

  const effectivePolicy = effectiveQuery.data;
  const profileMap: Partial<Record<TaskType, ModelProfileResponse>> = {};
  for (const p of listQuery.data?.items ?? []) {
    profileMap[p.task_type] = p;
  }

  const effectiveMap: Partial<Record<TaskType, ResolvedTaskProfile>> = {};
  for (const p of effectivePolicy?.profiles ?? []) {
    effectiveMap[p.task_type] = p;
  }

  return (
    <section className="px-4 py-5 lg:px-8 lg:py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Model profiles</h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure which model and provider each task type uses. Org overrides
          take precedence over environment defaults.
        </p>
      </div>

      {effectivePolicy && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
          <h2 className="mb-2 text-sm font-medium text-gray-700">
            Feature flags
          </h2>
          <div className="flex flex-wrap gap-3 text-xs text-gray-600">
            <span>
              Local LLM:{" "}
              <strong>
                {effectivePolicy.feature_local_llm_enabled
                  ? "enabled"
                  : "disabled"}
              </strong>
            </span>
            <span>
              Local embeddings:{" "}
              <strong>
                {effectivePolicy.feature_local_embeddings_enabled
                  ? "enabled"
                  : "disabled"}
              </strong>
            </span>
            <span>
              Provider fallback:{" "}
              <strong>
                {effectivePolicy.feature_fallback_enabled
                  ? "enabled"
                  : "disabled"}
              </strong>
            </span>
            <span>
              Request override:{" "}
              <strong>
                {effectivePolicy.feature_request_override_enabled
                  ? "enabled"
                  : "disabled"}
              </strong>
            </span>
          </div>
        </div>
      )}

      <div className="space-y-6">
        {ALL_TASK_TYPES.map((taskType) => {
          const resolved = effectiveMap[taskType];
          const existing = profileMap[taskType];
          return (
            <div key={taskType}>
              <div className="mb-2 flex items-center gap-2">
                <h2 className="text-base font-medium text-gray-800">
                  {TASK_LABELS[taskType]}
                </h2>
                {resolved && <SourceBadge source={resolved.source} />}
                {resolved && (
                  <span className="text-sm text-gray-500">
                    {resolved.provider_type} / {resolved.base_model}
                  </span>
                )}
              </div>
              <ProfileEditor
                taskType={taskType}
                existing={existing}
                onSave={handleSave}
                onDelete={handleDelete}
                isSaving={savingTask === taskType}
                isDeleting={deletingTask === taskType}
                saveError={mutationErrors[taskType] ?? null}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}
