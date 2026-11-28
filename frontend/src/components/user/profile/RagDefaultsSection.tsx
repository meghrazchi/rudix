"use client";

import { Brain } from "lucide-react";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  settingsConfidenceBounds,
  settingsTopKBounds,
} from "@/lib/settings-preferences";
import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function RagDefaultsSection({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const {
    t,
    ragForm,
    preferencesQuery,
    watchedTopK,
    watchedRerank,
    watchedDeveloperMode,
    confidencePercent,
    isHighTrust,
  } = ctl;

  return (
    <>
      {/* 3) AI/RAG Defaults */}
      {preferencesQuery.isLoading ? (
        <div className="rounded-2xl border border-[#c7c4d8] bg-white p-6">
          <LoadingState compact title={t("loadingPreferences")} />
        </div>
      ) : preferencesQuery.isError ? (
        <div className="rounded-2xl border border-[#c7c4d8] bg-white p-6">
          <ErrorState
            compact
            error={preferencesQuery.error}
            description={getApiErrorMessage(preferencesQuery.error)}
            onRetry={() => {
              void preferencesQuery.refetch();
            }}
          />
        </div>
      ) : (
        <>
          <section
            className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
            aria-label={t("aria.aiDefaultsSection")}
          >
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Brain size={20} className="text-[#3525cd]" />
                <h3 className="text-lg font-semibold text-[#1b1b24]">
                  {t("aiRagDefaults")}
                </h3>
              </div>
              {/* Expert mode toggle */}
              <button
                type="button"
                role="switch"
                aria-checked={watchedDeveloperMode}
                aria-label={t("expertModeToggle")}
                onClick={() =>
                  ragForm.setValue("developerMode", !watchedDeveloperMode, {
                    shouldDirty: true,
                  })
                }
                className={[
                  "rounded px-2 py-1 text-[10px] font-semibold tracking-wider uppercase transition-colors",
                  watchedDeveloperMode
                    ? "bg-[#3525cd] text-white"
                    : "bg-[#d0e1fb] text-[#54647a] hover:bg-[#b8d0f8]",
                ].join(" ")}
              >
                {t("expertMode")}
              </button>
            </div>

            <div className="space-y-8">
              {/* Top-K slider */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label
                    htmlFor="topKSlider"
                    className="text-sm font-semibold text-[#1b1b24]"
                  >
                    {t("topK.label")}
                  </label>
                  <span className="rounded bg-[#f0ecf9] px-2 py-0.5 font-mono text-sm text-[#3525cd]">
                    {watchedTopK ?? settingsTopKBounds.defaultValue}
                  </span>
                </div>
                <input
                  id="topKSlider"
                  type="range"
                  min={settingsTopKBounds.min}
                  max={settingsTopKBounds.max}
                  step={1}
                  aria-label={t("topK.label")}
                  {...ragForm.register("defaultTopK", {
                    valueAsNumber: true,
                  })}
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-[#c7c4d8] accent-[#3525cd]"
                />
                <div className="flex justify-between text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                  <span>{t("topK.precision")}</span>
                  <span>{t("topK.diversity")}</span>
                </div>
              </div>

              {/* Rerank toggle */}
              <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                <div>
                  <p className="text-sm font-semibold text-[#1b1b24]">
                    {t("rerank.title")}
                  </p>
                  <p className="text-xs text-[#464555]">
                    {t("rerank.description")}
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={watchedRerank}
                  onClick={() =>
                    ragForm.setValue("rerankEnabled", !watchedRerank, {
                      shouldDirty: true,
                    })
                  }
                  className={[
                    "relative flex h-6 w-12 shrink-0 items-center rounded-full px-1 transition-colors",
                    watchedRerank ? "bg-[#3525cd]" : "bg-[#c7c4d8]",
                  ].join(" ")}
                >
                  <div
                    className={[
                      "h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
                      watchedRerank ? "translate-x-6" : "translate-x-0",
                    ].join(" ")}
                  />
                </button>
              </div>

              {/* Confidence threshold */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label
                    htmlFor="confidenceSlider"
                    className="text-sm font-semibold text-[#1b1b24]"
                  >
                    {t("confidence.label")}
                  </label>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-[#f0ecf9] px-2 py-0.5 font-mono text-sm text-[#3525cd]">
                      {(confidencePercent / 100).toFixed(2)}
                    </span>
                    {isHighTrust && (
                      <span className="rounded bg-[#3525cd] px-2 py-0.5 text-[10px] font-semibold tracking-wider text-white uppercase">
                        {t("confidence.highTrust")}
                      </span>
                    )}
                  </div>
                </div>
                <input
                  id="confidenceSlider"
                  type="range"
                  min={settingsConfidenceBounds.min}
                  max={settingsConfidenceBounds.max}
                  step={1}
                  aria-label={t("confidence.label")}
                  {...ragForm.register("confidenceThreshold", {
                    valueAsNumber: true,
                  })}
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-[#c7c4d8] accent-[#3525cd]"
                />
              </div>
            </div>
          </section>

          {/* 4) Notifications */}
          <section
            className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
            aria-label={t("aria.notificationsSection")}
          >
            <div className="mb-6 flex items-center gap-3">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-[#3525cd]"
                aria-hidden="true"
              >
                <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
                <path d="M4 2C2.8 3.7 2 5.7 2 8" />
                <path d="M22 8c0-2.3-.8-4.3-2-6" />
              </svg>
              <h3 className="text-lg font-semibold text-[#1b1b24]">
                {t("notifications")}
              </h3>
            </div>

            <fieldset className="space-y-4">
              <legend className="sr-only">
                {t("notificationPreferences")}
              </legend>

              <label className="group flex cursor-pointer items-start gap-4">
                <input
                  type="checkbox"
                  {...ragForm.register("notifications.documentProcessing")}
                  className="mt-0.5 h-5 w-5 rounded border-[#c7c4d8] text-[#3525cd] transition-all focus:ring-[#3525cd]/20"
                />
                <div>
                  <span className="block text-sm font-semibold text-[#1b1b24] transition-colors group-hover:text-[#3525cd]">
                    {t("processingAlerts.title")}
                  </span>
                  <span className="block text-xs text-[#464555]">
                    {t("processingAlerts.description")}
                  </span>
                </div>
              </label>

              <label className="group flex cursor-pointer items-start gap-4">
                <input
                  type="checkbox"
                  {...ragForm.register("notifications.securityAlerts")}
                  className="mt-0.5 h-5 w-5 rounded border-[#c7c4d8] text-[#3525cd] transition-all focus:ring-[#3525cd]/20"
                />
                <div>
                  <span className="block text-sm font-semibold text-[#1b1b24] transition-colors group-hover:text-[#3525cd]">
                    {t("securityWarnings.title")}
                  </span>
                  <span className="block text-xs text-[#464555]">
                    {t("securityWarnings.description")}
                  </span>
                </div>
              </label>

              <label className="group flex cursor-pointer items-start gap-4 opacity-60">
                <input
                  type="checkbox"
                  {...ragForm.register("notifications.evaluationCompletion")}
                  className="mt-0.5 h-5 w-5 rounded border-[#c7c4d8] text-[#3525cd] transition-all focus:ring-[#3525cd]/20"
                />
                <div>
                  <span className="block text-sm font-semibold text-[#1b1b24] transition-colors group-hover:text-[#3525cd]">
                    {t("evalReports.title")}
                  </span>
                  <span className="block text-xs text-[#464555]">
                    {t("evalReports.description")}
                  </span>
                </div>
              </label>
            </fieldset>
          </section>
        </>
      )}
    </>
  );
}
