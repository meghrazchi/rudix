"use client";

import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import { OCR_LANGUAGES } from "@/lib/api/documents";

import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** OCR extraction metadata and OCR quality diagnostics (F232) for PDFs. */
export function DocumentOcrPanels({
  ctl,
  detail,
}: Omit<DetailSectionProps, "currentStatus">) {
  const {
    td,
    capabilities,
    ocrLangOverrideValue,
    setOcrLangOverrideValue,
    ocrLangOverrideOpen,
    setOcrLangOverrideOpen,
    ocrConfigMutation,
    ocrMetadata,
  } = ctl;
  return (
    <>
      {ocrMetadata && detail.file_type === "pdf" ? (
        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <div className="mb-3 flex items-center gap-2">
            <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("ocrExtraction")}
            </h4>
            <ContextualHelpLink topic="multilingual" />
          </div>
          <div className="space-y-2 text-sm text-[#2a2640]">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("ocrRequired")}</span>
              <span className="font-semibold">
                {ocrMetadata.required
                  ? td("errorYes").charAt(0).toUpperCase() +
                    td("errorYes").slice(1)
                  : td("errorNo").charAt(0).toUpperCase() +
                    td("errorNo").slice(1)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("detectionMode")}</span>
              <span className="font-semibold capitalize">
                {ocrMetadata.mode}
              </span>
            </div>
            {ocrMetadata.required ? (
              <>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#69637f]">{td("ocrStatus")}</span>
                  <span
                    className={`font-semibold capitalize ${ocrMetadata.status === "failed" ? "text-rose-600" : ocrMetadata.status === "partial" ? "text-amber-600" : "text-emerald-700"}`}
                  >
                    {ocrMetadata.status}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#69637f]">{td("languages")}</span>
                  <span className="font-semibold">
                    {ocrMetadata.languages.length > 0
                      ? ocrMetadata.languages.join(", ")
                      : "-"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#69637f]">{td("nativePages")}</span>
                  <span className="font-semibold">
                    {ocrMetadata.nativeTextPages}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#69637f]">{td("ocrPages")}</span>
                  <span className="font-semibold">
                    {ocrMetadata.pagesCompleted} / {ocrMetadata.pagesProcessed}
                  </span>
                </div>
                {ocrMetadata.durationMs !== null ? (
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[#69637f]">{td("ocrDuration")}</span>
                    <span className="font-semibold">
                      {(ocrMetadata.durationMs / 1000).toFixed(1)}s
                    </span>
                  </div>
                ) : null}
                {ocrMetadata.warnings.length > 0 ? (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="mb-1 text-xs font-semibold tracking-wide text-amber-700 uppercase">
                      {td("ocrWarnings")}
                    </p>
                    <ul className="space-y-1 text-xs text-amber-800">
                      {ocrMetadata.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-xs text-[#69637f]">{td("nativeTextNote")}</p>
            )}
          </div>
        </div>
      ) : null}

      {/* OCR quality diagnostics (F232) */}
      {detail.file_type === "pdf" &&
      (detail.ocr_quality_snapshot ||
        detail.ocr_languages_override ||
        capabilities.canOverrideLanguage) ? (
        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("ocrQuality")}
          </h4>
          <div className="space-y-2 text-sm text-[#2a2640]">
            {detail.ocr_languages_override ? (
              <div className="flex items-center justify-between gap-3">
                <span className="text-[#69637f]">{td("languageOverride")}</span>
                <span className="rounded-full bg-[#ece8ff] px-2 py-0.5 text-xs font-semibold text-[#3525cd]">
                  {detail.ocr_languages_override}
                </span>
              </div>
            ) : null}
            {detail.ocr_quality_snapshot ? (
              <>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#69637f]">{td("avgConfidence")}</span>
                  <span
                    className={`font-semibold ${
                      (detail.ocr_quality_snapshot.avg_confidence ?? 0) >= 0.7
                        ? "text-emerald-700"
                        : (detail.ocr_quality_snapshot.avg_confidence ?? 0) >=
                            0.3
                          ? "text-amber-600"
                          : "text-rose-600"
                    }`}
                  >
                    {detail.ocr_quality_snapshot.avg_confidence !== null &&
                    detail.ocr_quality_snapshot.avg_confidence !== undefined
                      ? `${(detail.ocr_quality_snapshot.avg_confidence * 100).toFixed(0)}%`
                      : "-"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#69637f]">{td("languagesUsed")}</span>
                  <span className="font-semibold">
                    {detail.ocr_quality_snapshot.languages.length > 0
                      ? detail.ocr_quality_snapshot.languages.join("+")
                      : "-"}
                  </span>
                </div>
                {detail.ocr_quality_snapshot.pages_failed > 0 ? (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="text-xs font-semibold text-amber-700">
                      {detail.ocr_quality_snapshot.pages_failed === 1
                        ? td("pagesFailed", {
                            count: detail.ocr_quality_snapshot.pages_failed,
                          })
                        : td("pagesFailedPlural", {
                            count: detail.ocr_quality_snapshot.pages_failed,
                          })}
                    </p>
                  </div>
                ) : null}
                {(detail.ocr_quality_snapshot.avg_confidence ?? 1) < 0.3 &&
                detail.ocr_quality_snapshot.pages_completed > 0 ? (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="text-xs font-semibold text-amber-700">
                      {td("lowConfidence")}
                    </p>
                  </div>
                ) : null}
              </>
            ) : null}
            {capabilities.canOverrideLanguage ? (
              <div className="mt-2 border-t border-[#e9e6f5] pt-2">
                {ocrLangOverrideOpen ? (
                  <div className="flex items-center gap-2">
                    <select
                      value={ocrLangOverrideValue}
                      onChange={(e) => setOcrLangOverrideValue(e.target.value)}
                      aria-label={td("selectOcrLanguage")}
                      className="flex-1 cursor-pointer rounded border border-[#c7c4d8] bg-white px-2 py-1 text-xs font-medium text-[#2a2640] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                    >
                      <option value="">{td("clearOverride")}</option>
                      {OCR_LANGUAGES.map((l) => (
                        <option key={l.code} value={l.code}>
                          {l.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={ocrConfigMutation.isPending}
                      onClick={() => {
                        ocrConfigMutation.mutate({
                          ocr_languages: ocrLangOverrideValue
                            ? [ocrLangOverrideValue]
                            : null,
                        });
                      }}
                      className="rounded bg-[#3525cd] px-2 py-1 text-xs font-semibold text-white hover:bg-[#2a1eb0] disabled:opacity-50"
                    >
                      {ocrConfigMutation.isPending ? td("saving") : td("save")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setOcrLangOverrideOpen(false)}
                      className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-medium text-[#69637f] hover:bg-[#f0ecf9]"
                    >
                      {td("cancel")}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setOcrLangOverrideValue("");
                      setOcrLangOverrideOpen(true);
                    }}
                    className="text-xs font-semibold text-[#3525cd] hover:underline"
                  >
                    {td("setOcrLanguage")}
                  </button>
                )}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
