"use client";

import { DocumentsTableRow } from "@/components/documents/list/DocumentsTableRow";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Documents table header and rows. */
export function DocumentsTable({ ctl }: { ctl: DocumentsPageController }) {
  const {
    tp,
    capabilities,
    setSelectedIds,
    selectableDocumentIds,
    allSelectableSelected,
    documents,
  } = ctl;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse bg-white text-left">
        <thead className="border-b border-[#e5e3f1] bg-[#f8f7ff]">
          <tr className="text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
            {capabilities.canDelete ? (
              <th className="px-4 py-3">
                <input
                  type="checkbox"
                  aria-label={tp("selectAll")}
                  checked={allSelectableSelected}
                  disabled={selectableDocumentIds.length === 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedIds(new Set(selectableDocumentIds));
                    } else {
                      setSelectedIds(new Set());
                    }
                  }}
                  className="h-4 w-4 rounded border-[#c9c6dc] text-[#3525cd] accent-[#3525cd]"
                />
              </th>
            ) : null}
            <th className="px-4 py-3">{tp("tableFilename")}</th>
            <th className="px-4 py-3">{tp("tableSource")}</th>
            <th className="px-4 py-3">{tp("tableType")}</th>
            <th className="px-4 py-3">{tp("tableStatus")}</th>
            <th className="px-4 py-3">{tp("freshnessLabel")}</th>
            <th className="px-4 py-3">{tp("qualityLabel")}</th>
            <th className="px-4 py-3 text-center">{tp("tablePages")}</th>
            <th className="px-4 py-3 text-center">{tp("tableChunks")}</th>
            <th className="px-4 py-3">{tp("tableCreated")}</th>
            <th className="px-4 py-3">{tp("tableUpdated")}</th>
            <th className="px-4 py-3 text-right">{tp("tableActions")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#ece9f6]">
          {documents.map((document) => (
            <DocumentsTableRow
              key={document.document_id}
              ctl={ctl}
              document={document}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
