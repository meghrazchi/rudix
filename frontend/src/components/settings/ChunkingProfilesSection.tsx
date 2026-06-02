"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Cpu, FlaskConical, Layers3, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  createChunkingProfile,
  getChunkingStrategyCatalog,
  listChunkingProfiles,
  previewChunkingProfile,
  setDefaultChunkingProfile,
  updateChunkingProfile,
} from "@/lib/api/chunking-profiles";
import { queryKeys } from "@/lib/api/query";
import { chunkingProfileConfigSchema } from "@/lib/schemas/chunking-profiles";
import { useAuthSession } from "@/lib/use-auth-session";

const chunkingProfileEditorSchema = z
  .object({
    name: z.string().trim().min(1, "Profile name is required.").max(100),
    strategy: z.string().trim().min(1, "Strategy is required."),
    chunk_size_tokens: z.coerce
      .number()
      .int()
      .min(100, "Chunk size must be at least 100 tokens.")
      .max(4000, "Chunk size must be 4000 tokens or fewer."),
    chunk_overlap_tokens: z.coerce
      .number()
      .int()
      .min(0, "Overlap cannot be negative.")
      .max(2000, "Overlap must be 2000 tokens or fewer."),
    language: z.string().trim().max(32).optional(),
    min_tokens: z
      .union([z.literal(""), z.coerce.number().int().min(1).max(500)])
      .optional(),
  })
  .superRefine((value, ctx) => {
    if (value.chunk_overlap_tokens >= value.chunk_size_tokens) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Overlap must be smaller than chunk size.",
        path: ["chunk_overlap_tokens"],
      });
    }
  });

const chunkingPreviewFormSchema = z.object({
  sample_text: z
    .string()
    .trim()
    .min(1, "Add sample text to preview chunking output.")
    .max(20_000, "Preview sample must be 20,000 characters or fewer."),
  file_type: z.enum(["txt", "md", "pdf", "docx"]),
});

type ChunkingProfileEditorFormValues = z.input<
  typeof chunkingProfileEditorSchema
>;
type ChunkingProfileEditorValues = z.output<typeof chunkingProfileEditorSchema>;
type ChunkingPreviewValues = z.infer<typeof chunkingPreviewFormSchema>;
type FeedbackState = { tone: "success" | "error"; message: string } | null;

const DEFAULT_PROFILE_NAME = "Organization Default";
const DEFAULT_PREVIEW_SAMPLE = `Employee Handbook

Annual Leave
Employees accrue annual leave monthly. Managers approve leave requests in the HR portal.

Sick Leave
Sick leave may be used for illness, medical appointments, or dependent care.

Escalations
Questions about leave policy should be directed to People Operations.`;

function asNullableString(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function asNullableNumber(
  value: ChunkingProfileEditorValues["min_tokens"],
): number | null {
  return typeof value === "number" ? value : null;
}

function isAdminLike(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function saveFeedbackClass(tone: "success" | "error"): string {
  return tone === "success"
    ? "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
    : "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
}

export function ChunkingProfilesSection() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role ?? null;
  const isAdmin = isAdminLike(role);
  const [saveFeedback, setSaveFeedback] = useState<FeedbackState>(null);
  const [previewFeedback, setPreviewFeedback] = useState<FeedbackState>(null);

  const editorForm = useForm<
    ChunkingProfileEditorFormValues,
    undefined,
    ChunkingProfileEditorValues
  >({
    resolver: zodResolver(chunkingProfileEditorSchema),
    defaultValues: {
      name: DEFAULT_PROFILE_NAME,
      strategy: "adaptive_hybrid",
      chunk_size_tokens: 700,
      chunk_overlap_tokens: 120,
      language: "",
      min_tokens: "",
    },
    mode: "onSubmit",
  });

  const previewForm = useForm<ChunkingPreviewValues>({
    resolver: zodResolver(chunkingPreviewFormSchema),
    defaultValues: {
      sample_text: DEFAULT_PREVIEW_SAMPLE,
      file_type: "txt",
    },
    mode: "onSubmit",
  });

  const strategiesQuery = useQuery({
    queryKey: queryKeys.admin.chunkingStrategies,
    queryFn: getChunkingStrategyCatalog,
    enabled: isAdmin,
    retry: false,
  });

  const profilesQuery = useQuery({
    queryKey: queryKeys.admin.chunkingProfiles,
    queryFn: listChunkingProfiles,
    enabled:
      isAdmin &&
      Boolean(strategiesQuery.data?.feature_chunking_profiles_enabled),
    retry: false,
  });

  const defaultProfile = useMemo(
    () =>
      profilesQuery.data?.profiles.find((profile) => profile.is_default) ??
      null,
    [profilesQuery.data],
  );

  const selectedStrategy = editorForm.watch("strategy");
  const strategyInfo = useMemo(
    () =>
      strategiesQuery.data?.strategies.find(
        (strategy) => strategy.name === selectedStrategy,
      ) ?? null,
    [selectedStrategy, strategiesQuery.data],
  );

  useEffect(() => {
    const fallbackConfig = strategiesQuery.data?.default_config;
    if (!fallbackConfig) {
      return;
    }

    if (defaultProfile) {
      editorForm.reset({
        name: defaultProfile.name,
        strategy: defaultProfile.config.strategy,
        chunk_size_tokens: defaultProfile.config.chunk_size_tokens,
        chunk_overlap_tokens: defaultProfile.config.chunk_overlap_tokens,
        language: defaultProfile.config.language ?? "",
        min_tokens: defaultProfile.config.min_tokens ?? "",
      });
      return;
    }

    editorForm.reset({
      name: DEFAULT_PROFILE_NAME,
      strategy: fallbackConfig.strategy,
      chunk_size_tokens: fallbackConfig.chunk_size_tokens,
      chunk_overlap_tokens: fallbackConfig.chunk_overlap_tokens,
      language: fallbackConfig.language ?? "",
      min_tokens: fallbackConfig.min_tokens ?? "",
    });
  }, [defaultProfile, editorForm, strategiesQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async (values: ChunkingProfileEditorValues) => {
      const config = chunkingProfileConfigSchema.parse({
        strategy: values.strategy,
        chunk_size_tokens: values.chunk_size_tokens,
        chunk_overlap_tokens: values.chunk_overlap_tokens,
        language: asNullableString(values.language),
        min_tokens: asNullableNumber(values.min_tokens),
        strategy_options: {},
      });

      if (defaultProfile) {
        return updateChunkingProfile(defaultProfile.profile_id, {
          name: values.name,
          config,
          set_as_default: true,
        });
      }

      return createChunkingProfile({
        name: values.name,
        config,
        set_as_default: true,
      });
    },
    onSuccess: async () => {
      setSaveFeedback({
        tone: "success",
        message: "Default chunking profile saved.",
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.chunkingProfiles,
      });
    },
    onError: (error) => {
      setSaveFeedback({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  const previewMutation = useMutation({
    mutationFn: async (values: ChunkingPreviewValues) => {
      const configValues =
        editorForm.getValues() as ChunkingProfileEditorValues;
      return previewChunkingProfile({
        config: {
          strategy: configValues.strategy,
          chunk_size_tokens: configValues.chunk_size_tokens,
          chunk_overlap_tokens: configValues.chunk_overlap_tokens,
          language: asNullableString(configValues.language),
          min_tokens: asNullableNumber(configValues.min_tokens),
          strategy_options: {},
        },
        sample_text: values.sample_text,
        file_type: values.file_type,
      });
    },
    onSuccess: () => {
      setPreviewFeedback(null);
    },
    onError: (error) => {
      setPreviewFeedback({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  const setDefaultMutation = useMutation({
    mutationFn: (profileId: string) => setDefaultChunkingProfile(profileId),
    onSuccess: async () => {
      setSaveFeedback({
        tone: "success",
        message: "Organization default profile updated.",
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.chunkingProfiles,
      });
    },
    onError: (error) => {
      setSaveFeedback({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Chunking profiles section"
    >
      <div className="mb-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Layers3 size={20} className="text-[#3525cd]" aria-hidden="true" />
          <div>
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Chunking Profiles
            </h2>
            <p className="text-sm text-[#5f5a74]">
              Configure the organization default chunking strategy and preview
              chunk behavior before re-indexing documents.
            </p>
          </div>
        </div>
        {strategiesQuery.data &&
        !strategiesQuery.data.feature_chunking_profiles_enabled ? (
          <span className="rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
            Feature disabled
          </span>
        ) : null}
      </div>

      {!isAdmin ? (
        <ForbiddenState
          compact
          title="Chunking profiles restricted"
          description="Chunking profile configuration is available to owner/admin roles only."
          backHref="/dashboard"
          backLabel="Back to dashboard"
        />
      ) : strategiesQuery.isLoading ? (
        <LoadingState compact title="Loading chunking strategy catalog..." />
      ) : strategiesQuery.isError ? (
        <ErrorState
          compact
          error={strategiesQuery.error}
          description={getApiErrorMessage(strategiesQuery.error)}
          onRetry={() => {
            void strategiesQuery.refetch();
          }}
        />
      ) : !strategiesQuery.data ? (
        <EmptyState
          compact
          title="Chunking strategy catalog unavailable."
          description="No chunking strategy data was returned by the API."
        />
      ) : (
        <div className="space-y-6">
          <div className="grid gap-3 lg:grid-cols-3">
            {strategiesQuery.data.strategies.map((strategy) => {
              const isSelected = strategy.name === selectedStrategy;
              return (
                <article
                  key={strategy.name}
                  className={`rounded-xl border p-4 ${
                    isSelected
                      ? "border-[#3525cd] bg-[#f5f2ff]"
                      : "border-[#e1ddea] bg-[#faf9ff]"
                  }`}
                >
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-[#1b1b24]">
                        {strategy.display_name}
                      </h3>
                      <p className="font-mono text-[11px] text-[#6a6780]">
                        {strategy.name}
                      </p>
                    </div>
                    {isSelected ? (
                      <span className="rounded-full bg-[#3525cd] px-2 py-1 text-[10px] font-bold tracking-wide text-white uppercase">
                        Selected
                      </span>
                    ) : null}
                  </div>
                  <p className="text-sm text-[#4d4963]">
                    {strategy.description}
                  </p>
                  <p className="mt-3 text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
                    Best for
                  </p>
                  <p className="mt-1 text-xs text-[#4d4963]">
                    {strategy.suitable_for.join(", ")}
                  </p>
                </article>
              );
            })}
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
            <div className="space-y-4 rounded-xl border border-[#e1ddea] bg-[#faf9ff] p-5">
              <div className="flex items-center gap-2">
                <Cpu size={18} className="text-[#3525cd]" aria-hidden="true" />
                <h3 className="text-base font-semibold text-[#1b1b24]">
                  Default profile editor
                </h3>
              </div>
              <p className="text-sm text-[#5f5a74]">
                Safe editable fields mirror the backend constraints. Advanced
                strategy options remain deployment-controlled.
              </p>

              {!strategiesQuery.data.feature_chunking_profiles_enabled ? (
                <div className="rounded-lg border border-slate-200 bg-white px-4 py-4 text-sm text-[#4d4963]">
                  Chunking profiles are turned off for this deployment. Review
                  the strategy catalog and defaults here, then enable
                  `FEATURE_ENABLE_CHUNKING_PROFILES` to persist organization
                  overrides.
                </div>
              ) : profilesQuery.isLoading ? (
                <LoadingState
                  compact
                  title="Loading organization profiles..."
                />
              ) : profilesQuery.isError ? (
                <ErrorState
                  compact
                  error={profilesQuery.error}
                  description={getApiErrorMessage(profilesQuery.error)}
                  onRetry={() => {
                    void profilesQuery.refetch();
                  }}
                />
              ) : (
                <form
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setSaveFeedback(null);
                    void editorForm.handleSubmit(async (values) => {
                      await saveMutation.mutateAsync(values);
                    })(event);
                  }}
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-1">
                      <label
                        htmlFor="chunking-profile-name"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Profile Name
                      </label>
                      <input
                        id="chunking-profile-name"
                        {...editorForm.register("name")}
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                      />
                      {editorForm.formState.errors.name ? (
                        <p role="alert" className="text-xs text-rose-700">
                          {editorForm.formState.errors.name.message}
                        </p>
                      ) : null}
                    </div>

                    <div className="space-y-1">
                      <label
                        htmlFor="chunking-strategy"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Strategy
                      </label>
                      <select
                        id="chunking-strategy"
                        {...editorForm.register("strategy")}
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                      >
                        {strategiesQuery.data.strategies.map((strategy) => (
                          <option key={strategy.name} value={strategy.name}>
                            {strategy.display_name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label
                        htmlFor="chunk-size-tokens"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Chunk Size Tokens
                      </label>
                      <input
                        id="chunk-size-tokens"
                        type="number"
                        min={100}
                        max={4000}
                        {...editorForm.register("chunk_size_tokens")}
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                      />
                    </div>

                    <div className="space-y-1">
                      <label
                        htmlFor="chunk-overlap-tokens"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Overlap Tokens
                      </label>
                      <input
                        id="chunk-overlap-tokens"
                        type="number"
                        min={0}
                        max={2000}
                        {...editorForm.register("chunk_overlap_tokens")}
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                      />
                      {editorForm.formState.errors.chunk_overlap_tokens ? (
                        <p role="alert" className="text-xs text-rose-700">
                          {
                            editorForm.formState.errors.chunk_overlap_tokens
                              .message
                          }
                        </p>
                      ) : null}
                    </div>

                    <div className="space-y-1">
                      <label
                        htmlFor="chunk-language"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Language Hint
                      </label>
                      <input
                        id="chunk-language"
                        {...editorForm.register("language")}
                        placeholder="Optional ISO code, e.g. en"
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                      />
                    </div>

                    <div className="space-y-1">
                      <label
                        htmlFor="chunk-min-tokens"
                        className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                      >
                        Minimum Tokens
                      </label>
                      <input
                        id="chunk-min-tokens"
                        type="number"
                        min={1}
                        max={500}
                        {...editorForm.register("min_tokens")}
                        placeholder="Optional"
                        className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                      />
                    </div>
                  </div>

                  <div className="rounded-lg border border-[#ddd7f6] bg-white px-4 py-3 text-sm text-[#4d4963]">
                    <p className="font-semibold text-[#1b1b24]">
                      Explainable defaults
                    </p>
                    <p className="mt-1">
                      System default:{" "}
                      <span className="font-semibold">
                        {strategiesQuery.data.default_config.strategy}
                      </span>{" "}
                      with{" "}
                      {strategiesQuery.data.default_config.chunk_size_tokens}{" "}
                      token chunks and{" "}
                      {strategiesQuery.data.default_config.chunk_overlap_tokens}{" "}
                      tokens of overlap.
                    </p>
                    {strategyInfo ? (
                      <p className="mt-2 text-[#5f5a74]">
                        {strategyInfo.description}
                      </p>
                    ) : null}
                  </div>

                  {profilesQuery.data &&
                  profilesQuery.data.profiles.length > 0 ? (
                    <div className="rounded-lg border border-[#e1ddea] bg-white px-4 py-3">
                      <p className="mb-3 text-sm font-semibold text-[#1b1b24]">
                        Existing profiles
                      </p>
                      <div className="space-y-2">
                        {profilesQuery.data.profiles.map((profile) => (
                          <div
                            key={profile.profile_id}
                            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#ece9f8] px-3 py-3"
                          >
                            <div>
                              <p className="text-sm font-semibold text-[#1b1b24]">
                                {profile.name}
                              </p>
                              <p className="text-xs text-[#5f5a74]">
                                {profile.config.strategy} ·{" "}
                                {profile.config.chunk_size_tokens}/
                                {profile.config.chunk_overlap_tokens}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              {profile.is_default ? (
                                <span className="rounded-full bg-[#3525cd] px-2 py-1 text-[10px] font-bold tracking-wide text-white uppercase">
                                  Default
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  disabled={setDefaultMutation.isPending}
                                  onClick={() => {
                                    void setDefaultMutation.mutateAsync(
                                      profile.profile_id,
                                    );
                                  }}
                                  className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  Make default
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <EmptyState
                      compact
                      title="No saved chunking profiles yet."
                      description="Saving the editor will create the organization default profile."
                    />
                  )}

                  {saveFeedback ? (
                    <p className={saveFeedbackClass(saveFeedback.tone)}>
                      {saveFeedback.message}
                    </p>
                  ) : null}

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={saveMutation.isPending}
                      className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {saveMutation.isPending
                        ? "Saving…"
                        : "Save default profile"}
                    </button>
                  </div>
                </form>
              )}
            </div>

            <div className="space-y-4 rounded-xl border border-[#e1ddea] bg-[#faf9ff] p-5">
              <div className="flex items-center gap-2">
                <FlaskConical
                  size={18}
                  className="text-[#3525cd]"
                  aria-hidden="true"
                />
                <h3 className="text-base font-semibold text-[#1b1b24]">
                  Preview current profile
                </h3>
              </div>
              <p className="text-sm text-[#5f5a74]">
                Preview returns chunk counts and metadata only. Raw chunk text
                is never included.
              </p>

              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  setPreviewFeedback(null);
                  void previewForm.handleSubmit(async (values) => {
                    await previewMutation.mutateAsync(values);
                  })(event);
                }}
              >
                <div className="space-y-1">
                  <label
                    htmlFor="chunk-preview-sample"
                    className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                  >
                    Sample Text
                  </label>
                  <textarea
                    id="chunk-preview-sample"
                    rows={10}
                    {...previewForm.register("sample_text")}
                    className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-3 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                  {previewForm.formState.errors.sample_text ? (
                    <p role="alert" className="text-xs text-rose-700">
                      {previewForm.formState.errors.sample_text.message}
                    </p>
                  ) : null}
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor="chunk-preview-file-type"
                    className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                  >
                    Sample File Type
                  </label>
                  <select
                    id="chunk-preview-file-type"
                    {...previewForm.register("file_type")}
                    className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  >
                    <option value="txt">TXT</option>
                    <option value="md">Markdown</option>
                    <option value="pdf">PDF</option>
                    <option value="docx">DOCX</option>
                  </select>
                </div>

                {previewFeedback ? (
                  <p className={saveFeedbackClass(previewFeedback.tone)}>
                    {previewFeedback.message}
                  </p>
                ) : null}

                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={previewMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#cbc5e6] bg-white px-4 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw size={16} aria-hidden="true" />
                    {previewMutation.isPending
                      ? "Previewing…"
                      : "Preview profile"}
                  </button>
                </div>
              </form>

              {previewMutation.data ? (
                <div className="space-y-4 rounded-lg border border-[#ddd7f6] bg-white p-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-lg border border-[#ece9f8] bg-[#faf9ff] p-3">
                      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                        Estimated chunk count
                      </p>
                      <p className="mt-1 text-lg font-semibold text-[#1b1b24]">
                        {previewMutation.data.chunk_count}
                      </p>
                    </div>
                    <div className="rounded-lg border border-[#ece9f8] bg-[#faf9ff] p-3">
                      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                        Strategy used
                      </p>
                      <p className="mt-1 text-lg font-semibold text-[#1b1b24]">
                        {previewMutation.data.strategy_used}
                      </p>
                    </div>
                    <div className="rounded-lg border border-[#ece9f8] bg-[#faf9ff] p-3">
                      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                        Average tokens
                      </p>
                      <p className="mt-1 text-lg font-semibold text-[#1b1b24]">
                        {previewMutation.data.avg_tokens}
                      </p>
                    </div>
                    <div className="rounded-lg border border-[#ece9f8] bg-[#faf9ff] p-3">
                      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                        Max tokens
                      </p>
                      <p className="mt-1 text-lg font-semibold text-[#1b1b24]">
                        {previewMutation.data.max_tokens}
                      </p>
                    </div>
                    <div className="rounded-lg border border-[#ece9f8] bg-[#faf9ff] p-3">
                      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                        Overlap
                      </p>
                      <p className="mt-1 text-lg font-semibold text-[#1b1b24]">
                        {
                          editorForm.getValues("chunk_overlap_tokens") as
                            | number
                            | ""
                            | undefined
                        }
                      </p>
                    </div>
                    <div className="rounded-lg border border-[#ece9f8] bg-[#faf9ff] p-3">
                      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                        Reason codes
                      </p>
                      <p className="mt-1 text-sm font-semibold text-[#1b1b24]">
                        {previewMutation.data.reason_codes.length > 0
                          ? previewMutation.data.reason_codes.join(", ")
                          : "Configured strategy"}
                      </p>
                    </div>
                  </div>

                  {previewMutation.data.warnings.length > 0 ? (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                      <p className="font-semibold">Warnings</p>
                      <ul className="mt-2 list-disc space-y-1 pl-4">
                        {previewMutation.data.warnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-[#1b1b24]">
                      Sample chunk metadata
                    </p>
                    <div className="space-y-2">
                      {previewMutation.data.sample_chunks.map((chunk) => (
                        <div
                          key={`${chunk.chunk_index}:${chunk.chunk_level}`}
                          className="rounded-lg border border-[#ece9f8] px-3 py-3 text-sm text-[#4d4963]"
                        >
                          <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
                            <span>Chunk #{chunk.chunk_index}</span>
                            <span>{chunk.token_count} tokens</span>
                            <span>Level {chunk.chunk_level}</span>
                            {chunk.is_parent ? (
                              <span className="rounded bg-[#3525cd] px-1.5 py-0.5 text-[10px] text-white">
                                Parent
                              </span>
                            ) : null}
                          </div>
                          <p className="mt-1 text-sm text-[#4d4963]">
                            {chunk.section_path ?? "No section path"}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
