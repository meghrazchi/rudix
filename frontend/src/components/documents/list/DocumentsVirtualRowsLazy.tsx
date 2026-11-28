"use client";

import { lazy, Suspense, type ComponentProps } from "react";

import { DocumentsTableRow } from "@/components/documents/list/DocumentsTableRow";
import type { DocumentsVirtualRows as DocumentsVirtualRowsContent } from "@/components/documents/list/DocumentsVirtualRows";
import {
  DOCUMENT_ROW_FALLBACK_COUNT,
  ESTIMATED_DOCUMENT_ROW_HEIGHT_PX,
} from "@/components/documents/list/virtual-rows";

type DocumentsVirtualRowsProps = ComponentProps<
  typeof DocumentsVirtualRowsContent
>;

// The virtualiser (@tanstack/react-virtual) is only needed above
// NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS rows, so it loads on demand (R07-03).
const DocumentsVirtualRowsContentLazy = lazy(() =>
  import("@/components/documents/list/DocumentsVirtualRows").then((module) => ({
    default: module.DocumentsVirtualRows,
  })),
);

/**
 * What the virtualiser renders at the top of the list: the first rows, then
 * one spacer row holding the estimated height of the rest, so the scroll
 * height does not jump when the virtualiser takes over.
 */
function DocumentsVirtualRowsFallback({
  ctl,
  documents,
  columnCount,
}: DocumentsVirtualRowsProps) {
  const visible = documents.slice(0, DOCUMENT_ROW_FALLBACK_COUNT);
  const paddingBottom =
    (documents.length - visible.length) * ESTIMATED_DOCUMENT_ROW_HEIGHT_PX;
  return (
    <>
      {visible.map((document, index) => (
        <DocumentsTableRow
          key={document.document_id}
          ctl={ctl}
          document={document}
          ariaRowIndex={index + 2}
        />
      ))}
      {paddingBottom > 0 ? (
        <tr aria-hidden="true" style={{ height: paddingBottom }}>
          <td colSpan={columnCount} />
        </tr>
      ) : null}
    </>
  );
}

export function DocumentsVirtualRows(props: DocumentsVirtualRowsProps) {
  return (
    <Suspense fallback={<DocumentsVirtualRowsFallback {...props} />}>
      <DocumentsVirtualRowsContentLazy {...props} />
    </Suspense>
  );
}
