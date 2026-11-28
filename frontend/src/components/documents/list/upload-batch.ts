import type { Dispatch, SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import type {
  UploadBatchRecord,
  UploadFeedbackState,
  UploadProgressItem,
  UploadProgressItemState,
  UploadProgressState,
} from "@/components/documents/DocumentsUploadModal";
import {
  maxUploadSizeMbFromEnv,
  validateUploadFile,
} from "@/components/documents/upload-validation";
import type { UploadDocumentMetadata } from "@/lib/api/documents";
import { uploadDocument } from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation } from "@/lib/api/query";
import { trackActivationEvent } from "@/lib/analytics";
import { extractRequestIdFromError } from "@/lib/forbidden";

import type { DocumentsPageTranslator } from "@/components/documents/list/documents-list-format";

export const MAX_UPLOAD_SIZE_MB = maxUploadSizeMbFromEnv();

function isAbortError(error: unknown): boolean {
  if (
    error instanceof DOMException &&
    error.name.toLowerCase() === "aborterror"
  ) {
    return true;
  }

  if (error instanceof Error) {
    const normalized = error.message.trim().toLowerCase();
    return normalized.includes("aborted");
  }

  return false;
}

export function updateUploadProgressItem(
  items: UploadProgressItem[],
  index: number,
  state: UploadProgressItemState,
  message?: string,
  requestId?: string | null,
): UploadProgressItem[] {
  return items.map((item, itemIndex) => {
    if (itemIndex !== index) {
      return item;
    }
    return {
      ...item,
      state,
      message: message ?? item.message,
      requestId: requestId ?? item.requestId,
    };
  });
}

export function hasCancelableUploads(
  progress: UploadProgressState | null,
): boolean {
  if (!progress) {
    return false;
  }

  return progress.items.some(
    (item) => item.state === "pending" || item.state === "uploading",
  );
}

export type UploadBatchContext = {
  tp: DocumentsPageTranslator;
  queryClient: QueryClient;
  uploadControllersRef: { current: Map<number, AbortController> };
  canceledUploadIndexesRef: { current: Set<number> };
  cancelAllUploadsRequestedRef: { current: boolean };
  currentBatchFilesRef: { current: File[] };
  currentBatchMetadataRef: { current: UploadDocumentMetadata };
  setActionFeedback: Dispatch<SetStateAction<string | null>>;
  setActionRequestId: Dispatch<SetStateAction<string | null>>;
  setIsUploading: Dispatch<SetStateAction<boolean>>;
  setUploadProgress: Dispatch<SetStateAction<UploadProgressState | null>>;
  setUploadFeedback: Dispatch<SetStateAction<UploadFeedbackState | null>>;
  setUploadHistory: Dispatch<SetStateAction<UploadBatchRecord[]>>;
  setSelectedDocumentId: Dispatch<SetStateAction<string | null>>;
  setChunksOffset: Dispatch<SetStateAction<number>>;
};

/** Uploads one batch sequentially with per-file progress, cancel, and summary feedback. */
export async function runUploadBatch(
  ctx: UploadBatchContext,
  files: File[],
  metadata: UploadDocumentMetadata = {},
): Promise<void> {
  const {
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
  } = ctx;
  setActionFeedback(null);
  setActionRequestId(null);

  if (files.length === 0) {
    return;
  }

  currentBatchFilesRef.current = files;
  currentBatchMetadataRef.current = metadata;
  uploadControllersRef.current.clear();
  canceledUploadIndexesRef.current.clear();
  cancelAllUploadsRequestedRef.current = false;

  const initialItems: UploadProgressItem[] = files.map((file) => ({
    fileName: file.name,
    state: "pending",
    message: null,
    requestId: null,
    canRetry: false,
  }));

  let completed = 0;
  let successCount = 0;
  let failedCount = 0;
  let canceledCount = 0;
  let latestSuccessDocumentId: string | null = null;
  let lastRequestId: string | null = null;
  let lastFailureMessage: string | null = null;
  let progressItems = initialItems;

  setIsUploading(true);
  setUploadProgress({
    total: files.length,
    completed,
    currentFileName: files[0]?.name ?? null,
    items: progressItems,
  });
  setUploadFeedback({
    state: "uploading",
    message: tp("uploadQueueStarting", { count: files.length }),
  });

  for (const [index, file] of files.entries()) {
    if (
      cancelAllUploadsRequestedRef.current ||
      canceledUploadIndexesRef.current.has(index)
    ) {
      canceledCount += 1;
      completed += 1;
      progressItems = updateUploadProgressItem(
        progressItems,
        index,
        "canceled",
        tp("feedbackUploadCanceled"),
      );
      setUploadProgress({
        total: files.length,
        completed,
        currentFileName: files[index + 1]?.name ?? null,
        items: progressItems,
      });
      continue;
    }

    const validationError = validateUploadFile(file, MAX_UPLOAD_SIZE_MB);
    if (validationError) {
      failedCount += 1;
      completed += 1;
      lastFailureMessage = validationError;
      progressItems = updateUploadProgressItem(
        progressItems,
        index,
        "failed",
        validationError,
      );
      setUploadProgress({
        total: files.length,
        completed,
        currentFileName: files[index + 1]?.name ?? null,
        items: progressItems,
      });
      setUploadFeedback({
        state: "failed",
        message: validationError,
      });
      continue;
    }

    const uploadController = new AbortController();
    uploadControllersRef.current.set(index, uploadController);
    progressItems = updateUploadProgressItem(progressItems, index, "uploading");
    setUploadProgress({
      total: files.length,
      completed,
      currentFileName: file.name,
      items: progressItems,
    });
    setUploadFeedback({
      state: "uploading",
      message: tp("uploadingProgress", {
        current: index + 1,
        total: files.length,
        filename: file.name,
      }),
    });

    try {
      const result = await uploadDocument(
        file,
        metadata,
        uploadController.signal,
      );
      uploadControllersRef.current.delete(index);

      if (canceledUploadIndexesRef.current.has(index)) {
        canceledCount += 1;
        completed += 1;
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          "canceled",
          tp("feedbackUploadCanceled"),
        );
        setUploadProgress({
          total: files.length,
          completed,
          currentFileName: files[index + 1]?.name ?? null,
          items: progressItems,
        });
        continue;
      }

      successCount += 1;
      latestSuccessDocumentId = result.document_id;
      completed += 1;
      const uploadedState = result.duplicate_detected
        ? "queued_duplicate"
        : "queued";
      progressItems = updateUploadProgressItem(
        progressItems,
        index,
        uploadedState,
        result.message,
      );
      setUploadProgress({
        total: files.length,
        completed,
        currentFileName: files[index + 1]?.name ?? null,
        items: progressItems,
      });
      setUploadFeedback({
        state: "queued",
        message: tp("uploadQueued", {
          filename: result.filename,
          completed,
          total: files.length,
        }),
      });
    } catch (error) {
      uploadControllersRef.current.delete(index);
      const canceled =
        canceledUploadIndexesRef.current.has(index) ||
        uploadController.signal.aborted ||
        isAbortError(error);

      if (canceled) {
        canceledCount += 1;
        completed += 1;
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          "canceled",
          tp("feedbackUploadCanceled"),
        );
        setUploadProgress({
          total: files.length,
          completed,
          currentFileName: files[index + 1]?.name ?? null,
          items: progressItems,
        });
        continue;
      }

      failedCount += 1;
      completed += 1;
      const errorMessage = getApiErrorMessage(error);
      const requestId = extractRequestIdFromError(error);
      lastRequestId = requestId;
      lastFailureMessage = errorMessage;
      progressItems = progressItems.map((item, itemIndex) => {
        if (itemIndex !== index) return item;
        return {
          ...item,
          state: "failed" as const,
          message: errorMessage,
          requestId: requestId ?? item.requestId,
          canRetry: true,
        };
      });
      setUploadProgress({
        total: files.length,
        completed,
        currentFileName: files[index + 1]?.name ?? null,
        items: progressItems,
      });
      setUploadFeedback({
        state: "failed",
        message: errorMessage,
        requestId,
      });
    }
  }

  uploadControllersRef.current.clear();
  cancelAllUploadsRequestedRef.current = false;

  if (successCount > 0) {
    void trackActivationEvent("activation.first_upload", {
      surface: "app",
      route: "/documents",
      pageKey: "documents",
      featureArea: "documents",
      count: successCount,
    });
    setSelectedDocumentId(latestSuccessDocumentId);
    setChunksOffset(0);
    await invalidateAfterMutation(queryClient, "document.upload");
  }

  setUploadHistory((prev) => {
    const record: UploadBatchRecord = {
      id: `batch-${Date.now()}`,
      startedAt: new Date().toISOString(),
      total: files.length,
      succeeded: successCount,
      failed: failedCount,
      canceled: canceledCount,
      files: files.map((f) => f.name),
    };
    return [record, ...prev].slice(0, 10);
  });

  setIsUploading(false);
  setUploadProgress((previous) =>
    previous
      ? {
          ...previous,
          completed: files.length,
          currentFileName: null,
          items: previous.items,
        }
      : previous,
  );

  if (successCount > 0 && failedCount === 0 && canceledCount === 0) {
    setUploadFeedback({
      state: "success",
      message: tp("uploadSuccess", {
        success: successCount,
        total: files.length,
      }),
    });
    return;
  }

  if (successCount > 0) {
    const remainder: string[] = [];
    if (failedCount > 0) {
      remainder.push(tp("uploadFailedCount", { count: failedCount }));
    }
    if (canceledCount > 0) {
      remainder.push(tp("uploadCanceledCount", { count: canceledCount }));
    }
    setUploadFeedback({
      state: "queued",
      message: tp("uploadPartial", {
        success: successCount,
        total: files.length,
        remainder: remainder.join(tp("listAnd")),
      }),
      requestId: lastRequestId,
    });
    return;
  }

  if (failedCount === 0 && canceledCount > 0) {
    setUploadFeedback({
      state: "canceled",
      message: tp("uploadCanceled", {
        canceled: canceledCount,
        total: files.length,
      }),
    });
    return;
  }

  setUploadFeedback({
    state: "failed",
    message:
      files.length === 1 && lastFailureMessage
        ? lastFailureMessage
        : tp("uploadAllFailed", { count: files.length }),
    requestId: lastRequestId,
  });
}
