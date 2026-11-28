"use client";

import { useVirtualizer } from "@tanstack/react-virtual";

import type { DocumentListItemResponse } from "@/lib/api/documents";

import { DocumentsTableRow } from "@/components/documents/list/DocumentsTableRow";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

export const ESTIMATED_DOCUMENT_ROW_HEIGHT_PX = 64;
const DOCUMENT_ROW_OVERSCAN = 8;

/**
 * Virtualised documents table body (R07-10), used above
 * NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS. Rows stay real `<tr>` elements in
 * document order with `aria-rowindex`; spacer rows keep the scroll height and
 * are hidden from assistive technology.
 */
export function DocumentsVirtualRows({
  ctl,
  documents,
  columnCount,
  scrollElement,
}: {
  ctl: DocumentsPageController;
  documents: DocumentListItemResponse[];
  columnCount: number;
  scrollElement: HTMLDivElement | null;
}) {
  const virtualizer = useVirtualizer({
    count: documents.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => ESTIMATED_DOCUMENT_ROW_HEIGHT_PX,
    overscan: DOCUMENT_ROW_OVERSCAN,
    getItemKey: (index) => documents[index]?.document_id ?? index,
  });

  const items = virtualizer.getVirtualItems();
  const paddingTop = items[0]?.start ?? 0;
  const paddingBottom =
    items.length > 0
      ? virtualizer.getTotalSize() - (items[items.length - 1]?.end ?? 0)
      : 0;

  return (
    <>
      {paddingTop > 0 ? (
        <tr aria-hidden="true" style={{ height: paddingTop }}>
          <td colSpan={columnCount} />
        </tr>
      ) : null}
      {items.map((item) => {
        const document = documents[item.index];
        if (!document) {
          return null;
        }
        return (
          <DocumentsTableRow
            key={document.document_id}
            ctl={ctl}
            document={document}
            ariaRowIndex={item.index + 2}
            virtualIndex={item.index}
            measureRef={virtualizer.measureElement}
          />
        );
      })}
      {paddingBottom > 0 ? (
        <tr aria-hidden="true" style={{ height: paddingBottom }}>
          <td colSpan={columnCount} />
        </tr>
      ) : null}
    </>
  );
}
