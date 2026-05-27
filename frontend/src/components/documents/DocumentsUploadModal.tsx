"use client";

import {
  useCallback,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";

import { useOverlayFocus } from "@/lib/use-overlay-focus";

type UploadState =
  | "idle"
  | "uploading"
  | "queued"
  | "success"
  | "failed"
  | "canceled";

export type UploadFeedbackState = {
  state: UploadState;
  message: string;
  requestId?: string | null;
};

export type UploadProgressItemState =
  | "pending"
  | "uploading"
  | "queued"
  | "success"
  | "failed"
  | "canceled";

export type UploadProgressItem = {
  fileName: string;
  state: UploadProgressItemState;
  message?: string | null;
  requestId?: string | null;
};

export type UploadProgressState = {
  total: number;
  completed: number;
  currentFileName: string | null;
  items: UploadProgressItem[];
};

type DocumentsUploadModalProps = {
  isOpen: boolean;
  canUpload: boolean;
  isUploading: boolean;
  acceptedTypesLabel: string;
  onRequestClose: () => void;
  onCancelAll: () => void;
  onCancelItem: (index: number) => void;
  onFilesSelected: (files: File[]) => Promise<void>;
  feedback: UploadFeedbackState | null;
  progress: UploadProgressState | null;
};

function feedbackClasses(state: UploadState): string {
  if (state === "failed") {
    return "mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
  }
  if (state === "queued") {
    return "mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800";
  }
  if (state === "success") {
    return "mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800";
  }
  if (state === "canceled") {
    return "mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700";
  }
  return "mt-3 rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]";
}

function progressStateClass(state: UploadProgressItemState): string {
  if (state === "failed") {
    return "bg-rose-100 text-rose-800";
  }
  if (state === "queued" || state === "success") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (state === "uploading") {
    return "bg-amber-100 text-amber-800";
  }
  if (state === "canceled") {
    return "bg-slate-200 text-slate-700";
  }
  return "bg-slate-100 text-slate-700";
}

function fileIconName(fileName: string): "picture_as_pdf" | "description" {
  if (fileName.toLowerCase().endsWith(".pdf")) {
    return "picture_as_pdf";
  }
  return "description";
}

export function DocumentsUploadModal({
  isOpen,
  canUpload,
  isUploading,
  acceptedTypesLabel,
  onRequestClose,
  onCancelAll,
  onCancelItem,
  onFilesSelected,
  feedback,
  progress,
}: DocumentsUploadModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleClose = useCallback(() => {
    onRequestClose();
  }, [onRequestClose]);

  useOverlayFocus({
    isOpen,
    containerRef: dialogRef,
    onClose: handleClose,
  });

  if (!isOpen) {
    return null;
  }

  async function handleFileUpload(files: File[]) {
    if (files.length === 0) {
      return;
    }
    await onFilesSelected(files);
  }

  async function onFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const files = Array.from(event.currentTarget.files ?? []);
    if (files.length === 0) {
      return;
    }
    await handleFileUpload(files);
    input.value = "";
  }

  async function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);

    if (!canUpload || isUploading) {
      return;
    }

    const files = Array.from(event.dataTransfer.files ?? []);
    if (files.length === 0) {
      return;
    }
    await handleFileUpload(files);
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (canUpload && !isUploading) {
      setDragActive(true);
    }
  }

  function onDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 bg-[#17172a]/40 backdrop-blur-sm"
        onClick={handleClose}
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="documents-upload-modal-title"
        aria-describedby="documents-upload-modal-description"
        className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-[#e5e3f1] bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e5e3f1] px-6 py-4">
          <div>
            <h3
              id="documents-upload-modal-title"
              className="text-xl font-bold text-[#1b1b24]"
            >
              Upload Documents
            </h3>
            <p
              id="documents-upload-modal-description"
              className="text-sm text-[#68647b]"
            >
              Drop files or click to select. Supported: {acceptedTypesLabel}.
            </p>
          </div>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={handleClose}
            aria-label="Close upload modal"
            className="rounded-full p-1 text-[#6f6b86] transition-colors hover:bg-[#f1eff9] hover:text-[#1b1b24]"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="space-y-6 p-6">
          <div
            onDrop={(event) => {
              void onDrop(event);
            }}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            className={`rounded-xl border-2 border-dashed p-8 text-center transition ${
              dragActive
                ? "border-[#3525cd] bg-[#f1efff]"
                : "border-[#d7d4e8] bg-[#faf9ff]"
            } ${canUpload && !isUploading ? "cursor-pointer" : "opacity-75"}`}
            role="button"
            tabIndex={canUpload && !isUploading ? 0 : -1}
            aria-label="Upload a document file"
            onClick={() => {
              if (!canUpload || isUploading) {
                return;
              }
              fileInputRef.current?.click();
            }}
            onKeyDown={(event) => {
              if (!canUpload || isUploading) {
                return;
              }
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.txt,.docx"
              multiple
              onChange={(event) => {
                void onFileInputChange(event);
              }}
              disabled={!canUpload || isUploading}
            />
            <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-[#3525cd]/10">
              <span className="material-symbols-outlined text-3xl text-[#3525cd]">
                {dragActive ? "upload_file" : "cloud_upload"}
              </span>
            </div>
            <p className="text-base font-semibold text-[#1b1b24]">
              {dragActive
                ? "Release to upload your files"
                : "Drop files here or click to browse"}
            </p>
            <p className="mt-1 text-sm text-[#68647b]">
              {isUploading
                ? "Uploads are running one by one. You can cancel each file."
                : "PDF, DOCX, TXT"}
            </p>
            {!canUpload ? (
              <p className="mt-2 text-xs text-[#6e6a86]">
                Your role can view documents but cannot upload files.
              </p>
            ) : null}
          </div>

          {!progress || progress.total === 0 ? (
            <div className="flex flex-wrap gap-2">
              <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
                PDF
              </span>
              <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
                DOCX
              </span>
              <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
                TXT
              </span>
            </div>
          ) : null}
        </div>

        {progress && progress.total > 0 ? (
          <div className="space-y-3 border-t border-[#e5e3f1] px-6 py-5">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-bold tracking-[0.08em] text-[#6a6780] uppercase">
                Uploading ({Math.max(progress.total - progress.completed, 0)})
              </h4>
              <span className="text-xs font-semibold text-[#4d4870]">
                Progress: {progress.completed}/{progress.total}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[#e7e3f6]">
              <div
                className="h-full bg-[#4b39db] transition-all"
                style={{
                  width: `${Math.min(
                    100,
                    Math.round((progress.completed / progress.total) * 100),
                  )}%`,
                }}
              />
            </div>
            <ul className="max-h-56 space-y-2 overflow-y-auto">
              {progress.items.map((item, index) => (
                <li
                  key={`${item.fileName}-${index}`}
                  className="rounded-xl border border-[#e5e3f1] bg-[#f8f7ff] p-3"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#3525cd]/10">
                      <span className="material-symbols-outlined text-[#3525cd]">
                        {fileIconName(item.fileName)}
                      </span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-[#1b1b24]">
                          {item.fileName}
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${progressStateClass(item.state)}`}
                        >
                          {item.state}
                        </span>
                      </div>
                      {item.state === "uploading" ? (
                        <p className="text-[11px] text-[#4b39db]">Uploading…</p>
                      ) : null}
                      {item.message ? (
                        <p className="mt-0.5 text-[11px] break-words text-[#5f5b7c]">
                          {item.message}
                          {item.requestId
                            ? ` (Trace ID: ${item.requestId})`
                            : ""}
                        </p>
                      ) : null}
                    </div>
                    {(item.state === "pending" || item.state === "uploading") &&
                    canUpload ? (
                      <button
                        type="button"
                        onClick={() => onCancelItem(index)}
                        aria-label={`Cancel upload for ${item.fileName}`}
                        className="rounded p-1 text-[#777587] transition-colors hover:text-[#ba1a1a]"
                      >
                        <span className="material-symbols-outlined">
                          cancel
                        </span>
                      </button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {feedback ? (
          <p
            role="status"
            className={`${feedbackClasses(feedback.state)} mx-6`}
          >
            {feedback.message}
            {feedback.requestId ? ` (Trace ID: ${feedback.requestId})` : ""}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-3 border-t border-[#e5e3f1] bg-[#f8f7ff] px-6 py-4">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg px-4 py-2 text-sm font-semibold text-[#2f2c45] transition-colors hover:bg-[#ebe8f7]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              if (!canUpload) {
                return;
              }
              if (isUploading) {
                onCancelAll();
                return;
              }
              fileInputRef.current?.click();
            }}
            disabled={!canUpload}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white shadow-md transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isUploading ? "Cancel All Uploads" : "Select Files To Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
