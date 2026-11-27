"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

export function NotionSetupGuide() {
  const t = useTranslations("connectors.setup.notionGuide");
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
            build_circle
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
            {/* Step 1 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                1
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">{t("step1Title")}</span> —{" "}
                {t("open")}{" "}
                <a
                  href="https://www.notion.so/my-integrations"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-blue-700"
                >
                  notion.so/my-integrations
                </a>
                , {t("step1Instruction")}
              </div>
            </li>

            {/* Step 2 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                2
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">{t("step2Title")}</span> —{" "}
                  {t("step2Instruction")}
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
              </div>
            </li>

            {/* Step 3 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">{t("step3Title")}</span> —{" "}
                  {t("step3Instruction")}
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
                  <div>CONNECTOR_OAUTH_CLIENTS=</div>
                  <div className="pl-2 text-[#464555]">
                    {'[{"provider_key":"notion",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_id":"<your-client-id>",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_secret":"<your-client-secret>"}]'}
                  </div>
                </div>
              </div>
            </li>

            {/* Step 4 */}
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
                  <div>page_ids, database_ids</div>
                  <div>include_comments, include_attachments</div>
                  <div>max_page_depth, import_property_metadata</div>
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
