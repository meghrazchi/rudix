"use client";

import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import { UPLOAD_LANGUAGES } from "@/lib/api/documents";

import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Detected language, confidence, source, and the admin language override. */
export function DocumentLanguagePanel({
  ctl,
  detail,
}: Omit<DetailSectionProps, "currentStatus">) {
  const {
    td,
    capabilities,
    langOverrideValue,
    setLangOverrideValue,
    langOverrideOpen,
    setLangOverrideOpen,
    langOverrideMutation,
  } = ctl;
  return (
    <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
      <div className="mb-3 flex items-center gap-2">
        <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {td("languageSection")}
        </h4>
        <ContextualHelpLink topic="multilingual" />
      </div>
      <div className="space-y-2 text-sm text-[#2a2640]">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[#69637f]">{td("detectedLanguage")}</span>
          <span className="font-semibold">
            {detail.language
              ? (UPLOAD_LANGUAGES.find((l) => l.code === detail.language)
                  ?.label ?? detail.language.toUpperCase())
              : "-"}
          </span>
        </div>
        {detail.language_confidence !== null &&
        detail.language_confidence !== undefined ? (
          <div className="flex items-center justify-between gap-3">
            <span className="text-[#69637f]">{td("confidence")}</span>
            <span className="font-semibold">
              {(detail.language_confidence * 100).toFixed(0)}%
            </span>
          </div>
        ) : null}
        {detail.language_source ? (
          <div className="flex items-center justify-between gap-3">
            <span className="text-[#69637f]">{td("source")}</span>
            <span className="rounded-full bg-[#ece8ff] px-2 py-0.5 text-xs font-semibold text-[#3525cd]">
              {detail.language_source.replace(/_/g, " ")}
            </span>
          </div>
        ) : null}
        {capabilities.canOverrideLanguage ? (
          <div className="mt-2 border-t border-[#e9e6f5] pt-2">
            {langOverrideOpen ? (
              <div className="flex items-center gap-2">
                <select
                  value={langOverrideValue}
                  onChange={(e) => setLangOverrideValue(e.target.value)}
                  aria-label={td("selectOverrideLanguage")}
                  className="flex-1 cursor-pointer rounded border border-[#c7c4d8] bg-white px-2 py-1 text-xs font-medium text-[#2a2640] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                >
                  <option value="">{td("clearOverride")}</option>
                  {UPLOAD_LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={langOverrideMutation.isPending}
                  onClick={() => {
                    langOverrideMutation.mutate({
                      language: langOverrideValue || null,
                    });
                  }}
                  className="rounded bg-[#3525cd] px-2 py-1 text-xs font-semibold text-white hover:bg-[#2a1eb0] disabled:opacity-50"
                >
                  {langOverrideMutation.isPending ? td("saving") : td("save")}
                </button>
                <button
                  type="button"
                  onClick={() => setLangOverrideOpen(false)}
                  className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-medium text-[#69637f] hover:bg-[#f0ecf9]"
                >
                  {td("cancel")}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setLangOverrideValue(detail.language ?? "");
                  setLangOverrideOpen(true);
                }}
                className="text-xs font-semibold text-[#3525cd] hover:underline"
              >
                {td("overrideLanguage")}
              </button>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
