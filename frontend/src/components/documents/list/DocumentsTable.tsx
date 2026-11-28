"use client";

import { useState } from "react";

import { tableVirtualizeMinRows } from "@/lib/pagination/virtualize";

import { DocumentsTableRow } from "@/components/documents/list/DocumentsTableRow";
import { DocumentsVirtualRows } from "@/components/documents/list/DocumentsVirtualRows";
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
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(
    null,
  );
  const virtualize = documents.length > tableVirtualizeMinRows();
  const columnCount = capabilities.canDelete ? 12 : 11;
  return (
    <div
      ref={setScrollElement}
      className={virtualize ? "max-h-[70vh] overflow-auto" : "overflow-x-auto"}
      data-testid={virtualize ? "documents-table-virtual" : undefined}
    >
      <table
        className="min-w-full border-collapse bg-white text-left"
        aria-rowcount={virtualize ? documents.length + 1 : undefined}
      >
        <thead
          className={`border-b border-[#e5e3f1] bg-[#f8f7ff] ${
            virtualize ? "sticky top-0 z-10" : ""
          }`}
        >
          <tr
            aria-rowindex={virtualize ? 1 : undefined}
            className="text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase"
          >
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
          {virtualize ? (
            <DocumentsVirtualRows
              ctl={ctl}
              documents={documents}
              columnCount={columnCount}
              scrollElement={scrollElement}
            />
          ) : (
            documents.map((document) => (
              <DocumentsTableRow
                key={document.document_id}
                ctl={ctl}
                document={document}
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
