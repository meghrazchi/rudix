"use client";

import { formatDate } from "@/components/documents/list/documents-list-format";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Promotional settings card and last-activity card. */
export function DocumentsActivityCards({
  ctl,
}: {
  ctl: DocumentsPageController;
}) {
  const { tp, documents, totalDocumentsCount } = ctl;
  return (
    <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
      <article className="relative overflow-hidden rounded-xl bg-gradient-to-br from-[#3525cd] to-[#4f46e5] p-6 text-white shadow-lg md:col-span-3">
        <div className="relative z-10 flex flex-col justify-between gap-4 md:flex-row md:items-center">
          <div className="max-w-2xl">
            <h2 className="text-2xl font-bold">{tp("maximize")}</h2>
            <p className="mt-1 text-sm text-white/90">{tp("maximizeDesc")}</p>
          </div>
          <button
            type="button"
            className="rounded-lg bg-white px-4 py-2 text-sm font-bold text-[#3525cd] shadow-md transition-transform hover:scale-105"
          >
            {tp("optimizeSettings")}
          </button>
        </div>
        <span className="material-symbols-outlined pointer-events-none absolute -top-8 -right-8 text-[180px] text-white/15">
          architecture
        </span>
      </article>
      <aside className="rounded-xl border border-[#e5e3f1] bg-white p-4 text-center shadow-sm">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#3525cd]/10">
          <span className="material-symbols-outlined text-[#3525cd]">
            history
          </span>
        </div>
        <p className="text-[10px] font-semibold tracking-[0.08em] text-[#6a6780] uppercase">
          {tp("lastActivity")}
        </p>
        <p className="mt-1 text-sm font-semibold text-[#1b1b24]">
          {totalDocumentsCount > 0 ? tp("recentUpload") : tp("noRecentUploads")}
        </p>
        <p className="text-xs text-[#68647b]">
          {documents[0]
            ? tp("updatedDate", { date: formatDate(documents[0].updated_at) })
            : tp("uploadStart")}
        </p>
      </aside>
    </section>
  );
}
