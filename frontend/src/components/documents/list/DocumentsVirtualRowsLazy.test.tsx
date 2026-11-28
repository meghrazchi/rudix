import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DocumentListItemResponse } from "@/lib/api/documents";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

// Keep the virtualiser module pending so the loading fallback stays rendered.
vi.mock(
  "@/components/documents/list/DocumentsVirtualRows",
  () => new Promise(() => {}),
);
vi.mock("@/components/documents/list/DocumentsTableRow", () => ({
  DocumentsTableRow: ({
    document,
    ariaRowIndex,
  }: {
    document: DocumentListItemResponse;
    ariaRowIndex?: number;
  }) => (
    <tr aria-rowindex={ariaRowIndex} data-testid="row">
      <td>{document.filename}</td>
    </tr>
  ),
}));

import { DocumentsVirtualRows } from "@/components/documents/list/DocumentsVirtualRowsLazy";
import {
  DOCUMENT_ROW_FALLBACK_COUNT,
  ESTIMATED_DOCUMENT_ROW_HEIGHT_PX,
} from "@/components/documents/list/virtual-rows";

function docs(count: number): DocumentListItemResponse[] {
  return Array.from(
    { length: count },
    (_, index) =>
      ({
        document_id: `doc-${index}`,
        filename: `file-${index}.pdf`,
      }) as DocumentListItemResponse,
  );
}

function renderRows(count: number) {
  return render(
    <table>
      <tbody>
        <DocumentsVirtualRows
          ctl={{} as DocumentsPageController}
          documents={docs(count)}
          columnCount={11}
          scrollElement={null}
        />
      </tbody>
    </table>,
  );
}

describe("DocumentsVirtualRows loading fallback", () => {
  it("renders the first rows and a spacer for the estimated rest", () => {
    const { container } = renderRows(250);
    const rows = screen.getAllByTestId("row");
    expect(rows).toHaveLength(DOCUMENT_ROW_FALLBACK_COUNT);
    expect(rows[0]).toHaveAttribute("aria-rowindex", "2");
    const spacer = container.querySelector('tr[aria-hidden="true"]');
    expect(spacer).toHaveStyle({
      height: `${(250 - DOCUMENT_ROW_FALLBACK_COUNT) * ESTIMATED_DOCUMENT_ROW_HEIGHT_PX}px`,
    });
    expect(spacer?.querySelector("td")).toHaveAttribute("colspan", "11");
  });

  it("omits the spacer when every row fits in the fallback", () => {
    const { container } = renderRows(3);
    expect(screen.getAllByTestId("row")).toHaveLength(3);
    expect(container.querySelector('tr[aria-hidden="true"]')).toBeNull();
  });
});
