"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { FileStack } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  DeploymentControlledBadge,
  FieldLabel,
  SaveFeedback,
  ToggleSwitch,
  ingestionDefaultsSchema,
  ingestionToForm,
  toList,
  toNullableNumber,
  type IngestionDefaultsFormValues,
  type SaveState,
} from "@/components/settings/organization/orgSettingsShared";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getIngestionDefaults,
  isOrganizationEndpointUnavailableError,
  updateIngestionDefaults,
  type getOrganizationCapabilities,
} from "@/lib/api/organization";
import { queryKeys } from "@/lib/api/query";

export function IngestionDefaultsSection({
  capabilities,
  isAdmin,
}: {
  capabilities: ReturnType<typeof getOrganizationCapabilities>;
  isAdmin: boolean;
}) {
  const t = useTranslations("settings.organization");

  const [ingestionSaveState, setIngestionSaveState] = useState<SaveState>(null);
  const ingestionLastSavedRef = useRef<IngestionDefaultsFormValues | null>(
    null,
  );

  const defaultIngestionValues: IngestionDefaultsFormValues = {
    allowedFileTypes: "",
    maxUploadSizeMb: "",
    maxPageCount: "",
    duplicateHandling: "skip",
    autoIndex: true,
    reindexPolicy: "on_update",
    retryPolicy: "once",
    defaultMetadataTags: "",
  };

  const ingestionForm = useForm<IngestionDefaultsFormValues>({
    resolver: zodResolver(ingestionDefaultsSchema),
    defaultValues: defaultIngestionValues,
    mode: "onSubmit",
  });

  const ingestionQuery = useQuery({
    queryKey: queryKeys.organization.ingestion,
    queryFn: getIngestionDefaults,
    enabled: capabilities.ingestionEnabled && isAdmin,
    retry: false,
  });

  useEffect(() => {
    if (!ingestionQuery.data) return;
    const values = ingestionToForm(ingestionQuery.data);
    ingestionLastSavedRef.current = values;
    ingestionForm.reset(values);
  }, [ingestionForm, ingestionQuery.data]);

  const ingestionSaveMutation = useMutation({
    mutationFn: (values: IngestionDefaultsFormValues) =>
      updateIngestionDefaults({
        allowed_file_types: toList(values.allowedFileTypes),
        max_upload_size_mb: toNullableNumber(values.maxUploadSizeMb),
        max_page_count: toNullableNumber(values.maxPageCount),
        duplicate_handling: values.duplicateHandling,
        auto_index: values.autoIndex,
        reindex_policy: values.reindexPolicy,
        retry_policy: values.retryPolicy,
        default_metadata_tags: toList(values.defaultMetadataTags),
      }),
    onSuccess: (updated) => {
      const values = ingestionToForm(updated);
      ingestionLastSavedRef.current = values;
      ingestionForm.reset(values);
      setIngestionSaveState({
        tone: "success",
        message: t("ingestion.saved"),
      });
    },
    onError: (error) => {
      setIngestionSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveIngestion(): Promise<void> {
    setIngestionSaveState(null);
    const valid = await ingestionForm.trigger();
    if (!valid) return;
    await ingestionSaveMutation.mutateAsync(ingestionForm.getValues());
  }

  function handleDiscardIngestion(): void {
    const last = ingestionLastSavedRef.current ?? defaultIngestionValues;
    ingestionForm.reset(last);
    setIngestionSaveState(null);
  }

  const watchedAutoIndex = ingestionForm.watch("autoIndex");

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Document and ingestion defaults section"
    >
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileStack size={20} className="text-[#3525cd]" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-[#1b1b24]">
            {t("ingestion.title")}
          </h2>
        </div>
        {!capabilities.ingestionEnabled && (
          <DeploymentControlledBadge label={t("deploymentControlled")} />
        )}
      </div>

      {!capabilities.ingestionEnabled ||
      isOrganizationEndpointUnavailableError(ingestionQuery.error) ? (
        <p className="text-sm text-[#777587]">{t("ingestion.unavailable")}</p>
      ) : !isAdmin ? (
        <ForbiddenState
          compact
          title={t("ingestion.restrictedTitle")}
          description={t("ingestion.restrictedDesc")}
          backHref="/dashboard"
          backLabel={t("backToDashboard")}
        />
      ) : ingestionQuery.isLoading ? (
        <LoadingState compact title={t("ingestion.loading")} />
      ) : ingestionQuery.isError ? (
        <ErrorState
          compact
          error={ingestionQuery.error}
          description={getApiErrorMessage(ingestionQuery.error)}
          onRetry={() => {
            void ingestionQuery.refetch();
          }}
        />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <FieldLabel htmlFor="ing-file-types">
                {t("ingestion.allowedFileTypes")}
              </FieldLabel>
              <input
                id="ing-file-types"
                {...ingestionForm.register("allowedFileTypes")}
                placeholder="pdf, docx, txt"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              <p className="text-xs text-[#777587]">{t("commaSeparated")}</p>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ing-max-size">
                {t("ingestion.maxUploadSizeMb")}
              </FieldLabel>
              <input
                id="ing-max-size"
                type="number"
                min={1}
                {...ingestionForm.register("maxUploadSizeMb")}
                placeholder="50"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ing-max-pages">
                {t("ingestion.maxPageCount")}
              </FieldLabel>
              <input
                id="ing-max-pages"
                type="number"
                min={1}
                {...ingestionForm.register("maxPageCount")}
                placeholder="500"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ing-duplicate">
                {t("ingestion.duplicateHandling")}
              </FieldLabel>
              <select
                id="ing-duplicate"
                {...ingestionForm.register("duplicateHandling")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="skip">{t("ingestion.dupSkip")}</option>
                <option value="replace">{t("ingestion.dupReplace")}</option>
                <option value="allow">{t("ingestion.dupAllow")}</option>
              </select>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ing-reindex">
                {t("ingestion.reindexPolicy")}
              </FieldLabel>
              <select
                id="ing-reindex"
                {...ingestionForm.register("reindexPolicy")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="on_update">
                  {t("ingestion.reindexOnUpdate")}
                </option>
                <option value="manual">{t("ingestion.reindexManual")}</option>
              </select>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ing-retry">
                {t("ingestion.retryPolicy")}
              </FieldLabel>
              <select
                id="ing-retry"
                {...ingestionForm.register("retryPolicy")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="never">{t("ingestion.retryNever")}</option>
                <option value="once">{t("ingestion.retryOnce")}</option>
                <option value="three_times">{t("ingestion.retryThree")}</option>
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <FieldLabel htmlFor="ing-metadata-tags">
              {t("ingestion.defaultMetadataTags")}
            </FieldLabel>
            <input
              id="ing-metadata-tags"
              {...ingestionForm.register("defaultMetadataTags")}
              placeholder="internal, knowledge-base"
              className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
            <p className="text-xs text-[#777587]">{t("commaSeparated")}</p>
          </div>

          <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
            <div>
              <label
                htmlFor="ing-auto-index"
                className="text-sm font-semibold text-[#1b1b24]"
              >
                {t("ingestion.autoIndex")}
              </label>
              <p className="text-xs text-[#464555]">
                {t("ingestion.autoIndexDesc")}
              </p>
            </div>
            <ToggleSwitch
              id="ing-auto-index"
              checked={watchedAutoIndex}
              onChange={(v) =>
                ingestionForm.setValue("autoIndex", v, {
                  shouldDirty: true,
                })
              }
            />
          </div>

          <div className="flex items-center justify-end gap-3">
            <SaveFeedback state={ingestionSaveState} />
            <button
              type="button"
              onClick={handleDiscardIngestion}
              disabled={ingestionSaveMutation.isPending}
              className="rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t("discard")}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleSaveIngestion();
              }}
              disabled={ingestionSaveMutation.isPending}
              aria-label={t("ingestion.saveAriaLabel")}
              className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {ingestionSaveMutation.isPending
                ? t("saving")
                : t("ingestion.save")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
