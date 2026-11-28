"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES } from "@/components/connectors/setup/oauthScopes";

export function MicrosoftSharePointOneDriveSetupGuide() {
  const t = useTranslations("connectors.setup.microsoftGuide");
  const [open, setOpen] = useState(false);
  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="w-full max-w-4xl overflow-hidden rounded-2xl border border-blue-200 bg-blue-50">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-blue-100/60"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-[20px] text-blue-700">
            cloud_done
          </span>
          <div>
            <div className="text-sm font-semibold text-blue-900">
              {t("title")}
            </div>
            <div className="text-xs text-blue-700">{t("subtitle")}</div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined shrink-0 text-[20px] text-blue-600 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="space-y-5 border-t border-blue-200 px-5 pt-4 pb-5">
          <p className="text-sm leading-relaxed text-blue-800">
            {t("introduction")}
          </p>

          <ol className="space-y-4">
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                1
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">{t("step1Title")}</span> —{" "}
                {t("open")}{" "}
                <a
                  href="https://portal.azure.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-blue-700"
                >
                  {t("azurePortal")}
                </a>
                , {t("step1Instruction")}
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                2
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">{t("step2Title")}</span> —{" "}
                {t("step2Instruction")}
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">{t("step3Title")}</span> —{" "}
                  {t("step3Instruction")}
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-blue-300 bg-white px-3 py-2">
                  <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title={t("copyCallback")}
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-blue-600 transition-colors hover:bg-blue-100"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      content_copy
                    </span>
                  </button>
                </div>
                <div className="divide-y divide-blue-100 overflow-hidden rounded-xl border border-blue-300 bg-white">
                  {MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES.map(
                    ({ scope, required }, index) => (
                      <div
                        key={scope}
                        className="flex items-center gap-3 px-3 py-2.5"
                      >
                        <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                          {scope}
                        </span>
                        <span className="hidden text-xs text-[#6a6780] sm:block">
                          {t(`scopeDescription${index + 1}`)}
                        </span>
                        {required ? (
                          <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold tracking-wide text-rose-700 uppercase">
                            {t("required")}
                          </span>
                        ) : (
                          <span className="shrink-0 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold tracking-wide text-[#3525cd] uppercase">
                            {t("recommended")}
                          </span>
                        )}
                      </div>
                    ),
                  )}
                </div>
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">{t("step4Title")}</span> —{" "}
                  {t("step4Instruction")}
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
                  <div>site_ids, drive_ids, folder_ids</div>
                  <div>allowed_file_types, include_folder_paths</div>
                  <div>exclude_folder_paths, sync_frequency_minutes</div>
                  <div>permission_import_behavior, max_file_size_mb</div>
                </div>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-white p-3 text-xs text-blue-800">
            <span className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-blue-600">
              lock
            </span>
            <span>{t("readOnlyNote")}</span>
          </div>
        </div>
      )}
    </div>
  );
}
