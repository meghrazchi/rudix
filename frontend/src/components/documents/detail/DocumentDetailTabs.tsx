"use client";

import { DocumentMetadataPanel } from "@/components/documents/DocumentMetadataPanel";
import { DocumentVersionHistoryPanel } from "@/components/documents/DocumentVersionHistoryPanel";
import { DocumentChunksTab } from "@/components/documents/detail/DocumentChunksTab";
import { DocumentErrorsTab } from "@/components/documents/detail/DocumentErrorsTab";
import { DocumentOverviewTab } from "@/components/documents/detail/DocumentOverviewTab";
import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Tab strip and active tab body of the document detail page. */
export function DocumentDetailTabs({
  ctl,
  detail,
  currentStatus,
}: DetailSectionProps) {
  const { documentId, td, capabilities, activeTab, setActiveTab, errorRows } =
    ctl;
  return (
    <section className="rounded-xl border border-[#e4e1f2] bg-white shadow-sm">
      <div className="flex flex-wrap items-center border-b border-[#e9e6f5] px-4">
        {(
          ["overview", "chunks", "errors", "versions", "metadata"] as const
        ).map((tabKey) => (
          <button
            key={tabKey}
            type="button"
            role="tab"
            aria-selected={activeTab === tabKey}
            onClick={() => setActiveTab(tabKey)}
            className={`px-4 py-3 text-sm font-semibold capitalize transition-colors ${
              activeTab === tabKey
                ? "border-b-2 border-[#3525cd] text-[#3525cd]"
                : "text-[#69637f] hover:text-[#2a2640]"
            }`}
          >
            {tabKey === "overview"
              ? td("tabOverview")
              : tabKey === "chunks"
                ? td("tabChunks")
                : tabKey === "versions"
                  ? td("tabVersions")
                  : tabKey === "metadata"
                    ? td("tabMetadata")
                    : td("tabErrors")}
            {tabKey === "errors" ? (
              <span className="ms-2 rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">
                {errorRows.length}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="space-y-4 p-4">
        {activeTab === "overview" ? (
          <DocumentOverviewTab
            ctl={ctl}
            detail={detail}
            currentStatus={currentStatus}
          />
        ) : null}
        {activeTab === "chunks" ? <DocumentChunksTab ctl={ctl} /> : null}
        {activeTab === "errors" ? <DocumentErrorsTab ctl={ctl} /> : null}
        {activeTab === "versions" ? (
          <section className="space-y-3">
            <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
              <h3 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                {td("versionHistory")}
              </h3>
              <p className="mb-4 text-xs text-[#69637f]">
                {td.rich("versionHistoryDescription", {
                  active: (chunks) => (
                    <span className="font-semibold text-emerald-700">
                      {chunks}
                    </span>
                  ),
                })}
              </p>
              <DocumentVersionHistoryPanel documentId={documentId} />
            </div>
          </section>
        ) : null}

        {activeTab === "metadata" ? (
          <section className="space-y-3">
            <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
              <DocumentMetadataPanel
                documentId={documentId}
                canEdit={capabilities.canDelete}
              />
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}
