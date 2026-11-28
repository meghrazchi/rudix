"use client";

import {
  useRef,
  useState,
  type Dispatch,
  type DragEvent,
  type SetStateAction,
} from "react";

import { useQueryClient } from "@tanstack/react-query";

import type {
  UploadBatchRecord,
  UploadFeedbackState,
  UploadProgressState,
} from "@/components/documents/DocumentsUploadModal";
import type { UploadDocumentMetadata } from "@/lib/api/documents";

import type { DocumentsPageTranslator } from "@/components/documents/list/documents-list-format";
import {
  hasCancelableUploads,
  runUploadBatch,
  updateUploadProgressItem,
} from "@/components/documents/list/upload-batch";

type UseDocumentUploadsArgs = {
  tp: DocumentsPageTranslator;
  capabilities: { canUpload: boolean };
  setSelectedDocumentId: Dispatch<SetStateAction<string | null>>;
  setChunksOffset: Dispatch<SetStateAction<number>>;
  setActionFeedback: Dispatch<SetStateAction<string | null>>;
  setActionRequestId: Dispatch<SetStateAction<string | null>>;
};

/** Upload modal state, the upload queue, cancel and retry, and page drag-and-drop. */
export function useDocumentUploads({
  tp,
  capabilities,
  setSelectedDocumentId,
  setChunksOffset,
  setActionFeedback,
  setActionRequestId,
}: UseDocumentUploadsArgs) {
  const queryClient = useQueryClient();
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadFeedback, setUploadFeedback] =
    useState<UploadFeedbackState | null>(null);
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgressState | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isPageDropActive, setIsPageDropActive] = useState(false);
  const [uploadHistory, setUploadHistory] = useState<UploadBatchRecord[]>([]);
  const uploadControllersRef = useRef<Map<number, AbortController>>(new Map());
  const canceledUploadIndexesRef = useRef<Set<number>>(new Set());
  const cancelAllUploadsRequestedRef = useRef(false);
  const currentBatchFilesRef = useRef<File[]>([]);
  const currentBatchMetadataRef = useRef<UploadDocumentMetadata>({});

  function cancelUploadAtIndex(index: number): void {
    canceledUploadIndexesRef.current.add(index);
    const controller = uploadControllersRef.current.get(index);
    if (controller) {
      controller.abort("upload-canceled-by-user");
    }

    setUploadProgress((previous) => {
      if (!previous || !previous.items[index]) {
        return previous;
      }

      const cancelMsg = tp("feedbackUploadCanceled");
      const nextItems = updateUploadProgressItem(
        previous.items,
        index,
        "canceled",
        cancelMsg,
      );

      return {
        ...previous,
        items: nextItems,
      };
    });

    setUploadFeedback({
      state: "canceled",
      message: tp("feedbackUploadCanceled"),
    });
  }

  function cancelAllUploads(): void {
    cancelAllUploadsRequestedRef.current = true;
    for (const controller of uploadControllersRef.current.values()) {
      controller.abort("upload-queue-canceled");
    }
    uploadControllersRef.current.clear();

    const cancelMsg = tp("feedbackUploadCanceled");
    setUploadProgress((previous) => {
      if (!previous) {
        return previous;
      }

      const nextItems = previous.items.map((item, index) => {
        if (item.state === "pending" || item.state === "uploading") {
          canceledUploadIndexesRef.current.add(index);
          return {
            ...item,
            state: "canceled" as const,
            message: cancelMsg,
          };
        }
        return item;
      });

      return {
        ...previous,
        items: nextItems,
      };
    });

    setUploadFeedback({
      state: "canceled",
      message: tp("feedbackUploadQueueCanceled"),
    });
  }

  function handleUploadModalClose(): void {
    if (hasCancelableUploads(uploadProgress) || isUploading) {
      cancelAllUploads();
    }
    setIsUploadModalOpen(false);
  }

  async function handleFileUpload(
    files: File[],
    metadata: UploadDocumentMetadata = {},
  ): Promise<void> {
    await runUploadBatch(
      {
        tp,
        queryClient,
        uploadControllersRef,
        canceledUploadIndexesRef,
        cancelAllUploadsRequestedRef,
        currentBatchFilesRef,
        currentBatchMetadataRef,
        setActionFeedback,
        setActionRequestId,
        setIsUploading,
        setUploadProgress,
        setUploadFeedback,
        setUploadHistory,
        setSelectedDocumentId,
        setChunksOffset,
      },
      files,
      metadata,
    );
  }

  function handleRetryItem(index: number): void {
    const file = currentBatchFilesRef.current[index];
    if (!file || isUploading) {
      return;
    }

    setUploadProgress((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        completed: Math.max(0, prev.completed - 1),
        total: prev.total,
        items: prev.items.map((item, i) => {
          if (i !== index) return item;
          return {
            ...item,
            state: "pending" as const,
            message: null,
            requestId: null,
            canRetry: false,
          };
        }),
      };
    });

    void (async () => {
      await handleFileUpload([file], currentBatchMetadataRef.current);
    })();
  }

  function handlePageUploadDragOver(event: DragEvent<HTMLButtonElement>): void {
    event.preventDefault();
    event.stopPropagation();
    if (!capabilities.canUpload || isUploading) {
      return;
    }
    setIsPageDropActive(true);
  }

  function handlePageUploadDragLeave(
    event: DragEvent<HTMLButtonElement>,
  ): void {
    event.preventDefault();
    event.stopPropagation();
    setIsPageDropActive(false);
  }

  async function handlePageUploadDrop(
    event: DragEvent<HTMLButtonElement>,
  ): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    setIsPageDropActive(false);

    if (!capabilities.canUpload || isUploading) {
      return;
    }

    const files = Array.from(event.dataTransfer.files ?? []);
    if (files.length === 0) {
      return;
    }

    setIsUploadModalOpen(true);
    await handleFileUpload(files, {});
  }

  return {
    isUploadModalOpen,
    setIsUploadModalOpen,
    uploadFeedback,
    uploadProgress,
    isUploading,
    isPageDropActive,
    uploadHistory,
    cancelUploadAtIndex,
    cancelAllUploads,
    handleUploadModalClose,
    handleFileUpload,
    handleRetryItem,
    handlePageUploadDragOver,
    handlePageUploadDragLeave,
    handlePageUploadDrop,
  };
}
