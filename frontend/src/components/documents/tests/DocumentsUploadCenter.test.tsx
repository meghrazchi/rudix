import { describe, expect, it, vi } from "vitest";

import { act, render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  DocumentsUploadModal,
  type UploadProgressState,
  type UploadBatchRecord,
} from "@/components/documents/DocumentsUploadModal";
import type { CollectionListItemResponse } from "@/lib/api/collections";
import type { UploadDocumentMetadata } from "@/lib/api/documents";

const noop = async () => {};
const noopSync = () => {};

const defaultProps = {
  isOpen: true,
  canUpload: true,
  isUploading: false,
  acceptedTypesLabel: "PDF, DOCX, TXT",
  collections: [] as CollectionListItemResponse[],
  onRequestClose: noopSync,
  onCancelAll: noopSync,
  onCancelItem: noopSync,
  onRetryItem: noopSync,
  onFilesSelected: noop,
  feedback: null,
  progress: null,
  uploadHistory: [] as UploadBatchRecord[],
};

describe("DocumentsUploadModal (upload center)", () => {
  it("renders the drop zone and title", () => {
    render(<DocumentsUploadModal {...defaultProps} />);
    expect(screen.getByText("Upload Center")).toBeInTheDocument();
    expect(
      screen.getByText(/Drop files here or click to browse/i),
    ).toBeInTheDocument();
  });

  it("does not render when isOpen is false", () => {
    render(<DocumentsUploadModal {...defaultProps} isOpen={false} />);
    expect(screen.queryByText("Upload Center")).not.toBeInTheDocument();
  });

  it("calls onRequestClose when close button is clicked", async () => {
    const onRequestClose = vi.fn();
    render(
      <DocumentsUploadModal
        {...defaultProps}
        onRequestClose={onRequestClose}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onRequestClose).toHaveBeenCalledOnce();
  });

  it("shows read-only message when canUpload is false", () => {
    render(<DocumentsUploadModal {...defaultProps} canUpload={false} />);
    expect(
      screen.getByText(/Your role can view documents but cannot upload files/i),
    ).toBeInTheDocument();
  });

  it("shows uploading text when isUploading is true", () => {
    render(<DocumentsUploadModal {...defaultProps} isUploading={true} />);
    expect(screen.getByText(/Uploads are running/i)).toBeInTheDocument();
  });

  it("shows file type badges when no progress", () => {
    render(<DocumentsUploadModal {...defaultProps} />);
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("DOCX")).toBeInTheDocument();
    expect(screen.getByText("TXT")).toBeInTheDocument();
  });

  it("does not show file type badges during upload progress", () => {
    const progress: UploadProgressState = {
      total: 1,
      completed: 0,
      currentFileName: "report.pdf",
      items: [{ fileName: "report.pdf", state: "uploading" }],
    };
    render(<DocumentsUploadModal {...defaultProps} progress={progress} />);
    const badges = screen.queryAllByText(/^PDF$|^DOCX$|^TXT$/);
    expect(badges.length).toBe(0);
  });

  describe("upload queue", () => {
    it("shows queue items with correct state badges", () => {
      const progress: UploadProgressState = {
        total: 3,
        completed: 1,
        currentFileName: "b.pdf",
        items: [
          { fileName: "a.pdf", state: "queued" },
          { fileName: "b.pdf", state: "uploading" },
          {
            fileName: "c.pdf",
            state: "failed",
            message: "Server error",
            canRetry: true,
          },
        ],
      };
      render(<DocumentsUploadModal {...defaultProps} progress={progress} />);
      expect(screen.getByText("a.pdf")).toBeInTheDocument();
      expect(screen.getByText("b.pdf")).toBeInTheDocument();
      expect(screen.getByText("c.pdf")).toBeInTheDocument();
      expect(screen.getByText(/queued for indexing/i)).toBeInTheDocument();
      expect(screen.getByText(/Server error/i)).toBeInTheDocument();
    });

    it("shows retry button only for failed items with canRetry", () => {
      const onRetryItem = vi.fn();
      const progress: UploadProgressState = {
        total: 2,
        completed: 1,
        currentFileName: null,
        items: [
          {
            fileName: "good.pdf",
            state: "queued",
            canRetry: false,
          },
          {
            fileName: "bad.pdf",
            state: "failed",
            message: "Network error",
            canRetry: true,
          },
        ],
      };
      render(
        <DocumentsUploadModal
          {...defaultProps}
          progress={progress}
          onRetryItem={onRetryItem}
        />,
      );
      const retryBtn = screen.getByRole("button", {
        name: /retry upload for bad\.pdf/i,
      });
      expect(retryBtn).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /retry upload for good\.pdf/i }),
      ).not.toBeInTheDocument();
      fireEvent.click(retryBtn);
      expect(onRetryItem).toHaveBeenCalledWith(1);
    });

    it("shows cancel button for pending and uploading items", () => {
      const onCancelItem = vi.fn();
      const progress: UploadProgressState = {
        total: 2,
        completed: 0,
        currentFileName: "b.pdf",
        items: [
          { fileName: "a.pdf", state: "pending" },
          { fileName: "b.pdf", state: "uploading" },
        ],
      };
      render(
        <DocumentsUploadModal
          {...defaultProps}
          progress={progress}
          onCancelItem={onCancelItem}
        />,
      );
      const cancelBtns = screen.getAllByRole("button", {
        name: /cancel upload for/i,
      });
      expect(cancelBtns).toHaveLength(2);
      fireEvent.click(cancelBtns[0]);
      expect(onCancelItem).toHaveBeenCalledWith(0);
    });

    it("shows cancel-all button when there are active uploads", () => {
      const onCancelAll = vi.fn();
      const progress: UploadProgressState = {
        total: 2,
        completed: 0,
        currentFileName: "a.pdf",
        items: [
          { fileName: "a.pdf", state: "uploading" },
          { fileName: "b.pdf", state: "pending" },
        ],
      };
      render(
        <DocumentsUploadModal
          {...defaultProps}
          isUploading={true}
          progress={progress}
          onCancelAll={onCancelAll}
        />,
      );
      const cancelAll = screen.getByRole("button", { name: /cancel all/i });
      fireEvent.click(cancelAll);
      expect(onCancelAll).toHaveBeenCalledOnce();
    });

    it("shows progress bar with correct width for partial completion", () => {
      const progress: UploadProgressState = {
        total: 4,
        completed: 2,
        currentFileName: null,
        items: [
          { fileName: "a.pdf", state: "queued" },
          { fileName: "b.pdf", state: "queued" },
          { fileName: "c.pdf", state: "pending" },
          { fileName: "d.pdf", state: "pending" },
        ],
      };
      const { container } = render(
        <DocumentsUploadModal {...defaultProps} progress={progress} />,
      );
      const bar = container.querySelector(".bg-\\[\\#4b39db\\]");
      expect(bar).toHaveStyle({ width: "50%" });
    });
  });

  describe("feedback messages", () => {
    it("shows success feedback", () => {
      render(
        <DocumentsUploadModal
          {...defaultProps}
          feedback={{ state: "success", message: "All files uploaded!" }}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        "All files uploaded!",
      );
    });

    it("shows failed feedback with trace ID", () => {
      render(
        <DocumentsUploadModal
          {...defaultProps}
          feedback={{
            state: "failed",
            message: "Upload failed.",
            requestId: "abc-123",
          }}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent("abc-123");
    });

    it("shows canceled feedback", () => {
      render(
        <DocumentsUploadModal
          {...defaultProps}
          feedback={{ state: "canceled", message: "Upload canceled by user." }}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        "Upload canceled by user.",
      );
    });
  });

  describe("upload history", () => {
    it("shows history button when there are past batches", () => {
      const history: UploadBatchRecord[] = [
        {
          id: "batch-1",
          startedAt: new Date().toISOString(),
          total: 2,
          succeeded: 1,
          failed: 1,
          canceled: 0,
          files: ["doc1.pdf", "doc2.pdf"],
        },
      ];
      render(
        <DocumentsUploadModal {...defaultProps} uploadHistory={history} />,
      );
      expect(
        screen.getByRole("button", { name: /upload history/i }),
      ).toBeInTheDocument();
    });

    it("does not show history button when history is empty", () => {
      render(<DocumentsUploadModal {...defaultProps} uploadHistory={[]} />);
      expect(
        screen.queryByRole("button", { name: /upload history/i }),
      ).not.toBeInTheDocument();
    });

    it("toggles history panel on click", async () => {
      const history: UploadBatchRecord[] = [
        {
          id: "batch-1",
          startedAt: new Date().toISOString(),
          total: 1,
          succeeded: 1,
          failed: 0,
          canceled: 0,
          files: ["report.pdf"],
        },
      ];
      render(
        <DocumentsUploadModal {...defaultProps} uploadHistory={history} />,
      );
      const btn = screen.getByRole("button", { name: /upload history/i });
      expect(screen.queryByText(/Upload History/i)).not.toBeInTheDocument();
      await userEvent.click(btn);
      expect(screen.getByText(/Upload History/i)).toBeInTheDocument();
    });
  });

  describe("metadata form", () => {
    it("expands metadata section on toggle", async () => {
      render(<DocumentsUploadModal {...defaultProps} />);
      const toggle = screen.getByRole("button", {
        name: /upload details/i,
      });
      expect(screen.queryByLabelText(/Tags/i)).not.toBeInTheDocument();
      await userEvent.click(toggle);
      expect(screen.getByLabelText(/Tags/i)).toBeInTheDocument();
    });

    it("shows collection selector when collections are provided", async () => {
      const collections: CollectionListItemResponse[] = [
        {
          collection_id: "col-1",
          name: "Legal Documents",
          description: null,
          owner_id: "u-1",
          owner_email: null,
          document_count: 5,
          indexed_count: 5,
          access_policy: "org_wide",
          is_dynamic: false,
          last_rule_evaluated_at: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ];
      render(
        <DocumentsUploadModal {...defaultProps} collections={collections} />,
      );
      await userEvent.click(
        screen.getByRole("button", { name: /upload details/i }),
      );
      expect(screen.getByText("Legal Documents")).toBeInTheDocument();
    });

    it("passes metadata to onFilesSelected when files are submitted", async () => {
      const onFilesSelected = vi.fn().mockResolvedValue(undefined);
      render(
        <DocumentsUploadModal
          {...defaultProps}
          onFilesSelected={onFilesSelected}
        />,
      );
      await userEvent.click(
        screen.getByRole("button", { name: /upload details/i }),
      );
      const tagsInput = screen.getByLabelText(/Tags/i);
      await userEvent.type(tagsInput, "compliance, legal");

      const dropZone = screen.getByRole("button", {
        name: /Upload a document file/i,
      });

      const file = new File(["content"], "doc.pdf", {
        type: "application/pdf",
      });

      await act(async () => {
        fireEvent.drop(dropZone, {
          dataTransfer: { files: [file] },
        });
      });

      await vi.waitFor(() => {
        expect(onFilesSelected).toHaveBeenCalledOnce();
      });

      const [, metadata] = onFilesSelected.mock.calls[0] as [
        File[],
        UploadDocumentMetadata,
      ];
      expect(metadata.tags).toEqual(["compliance", "legal"]);
    });
  });
});
