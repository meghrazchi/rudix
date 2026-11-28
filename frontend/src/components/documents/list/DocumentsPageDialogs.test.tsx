import { screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { DeleteConfirmModal } from "@/components/documents/list/DocumentsPageDialogs";
import { renderWithProviders } from "@/test/render";

beforeAll(async () => {
  // Warm the on-demand module so the lazy import resolves promptly.
  await import("@/components/documents/DeleteConfirmModal");
});

describe("DocumentsPageDialogs (on-demand dialogs)", () => {
  it("renders nothing and loads nothing before the first open", () => {
    const { container } = renderWithProviders(
      <DeleteConfirmModal
        open={false}
        filenames={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the dialog once opened, hides it when closed and reopens it", async () => {
    const props = {
      filenames: ["a.pdf"],
      onConfirm: vi.fn(),
      onCancel: vi.fn(),
    };
    const { rerender } = renderWithProviders(
      <DeleteConfirmModal open {...props} />,
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    rerender(<DeleteConfirmModal open={false} {...props} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    rerender(<DeleteConfirmModal open {...props} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
