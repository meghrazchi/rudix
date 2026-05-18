"use client";

import { useCallback, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { useOverlayFocus } from "@/lib/use-overlay-focus";

type UploadState = "idle" | "uploading" | "queued" | "success" | "failed";

export type UploadFeedbackState = {
  state: UploadState;
  message: string;
  requestId?: string | null;
};

type DocumentsUploadModalProps = {
  isOpen: boolean;
  canUpload: boolean;
  isUploading: boolean;
  acceptedTypesLabel: string;
  onClose: () => void;
  onFileSelected: (file: File) => Promise<void>;
  feedback: UploadFeedbackState | null;
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
  return "mt-3 rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]";
}

export function DocumentsUploadModal({
  isOpen,
  canUpload,
  isUploading,
  acceptedTypesLabel,
  onClose,
  onFileSelected,
  feedback,
}: DocumentsUploadModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleClose = useCallback(() => {
    if (isUploading) {
      return;
    }
    onClose();
  }, [isUploading, onClose]);

  useOverlayFocus({
    isOpen,
    containerRef: dialogRef,
    onClose: handleClose,
  });

  if (!isOpen) {
    return null;
  }

  async function handleFileUpload(file: File) {
    await onFileSelected(file);
  }

  async function onFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const nextFile = event.currentTarget.files?.[0];
    if (!nextFile) {
      return;
    }
    await handleFileUpload(nextFile);
    input.value = "";
  }

  async function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);

    if (!canUpload || isUploading) {
      return;
    }

    const nextFile = event.dataTransfer.files?.[0];
    if (!nextFile) {
      return;
    }
    await handleFileUpload(nextFile);
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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#17172a]/55 px-4"
      onClick={handleClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="documents-upload-modal-title"
        aria-describedby="documents-upload-modal-description"
        className="w-full max-w-2xl rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 id="documents-upload-modal-title" className="text-lg font-bold text-[#2a2640]">
              Upload document
            </h3>
            <p id="documents-upload-modal-description" className="text-sm text-[#68647b]">
              Drop one file or click to select. Supported formats: {acceptedTypesLabel}.
            </p>
          </div>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={handleClose}
            disabled={isUploading}
            className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
          >
            Close
          </button>
        </div>

        <div
          onDrop={(event) => {
            void onDrop(event);
          }}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          className={`rounded-xl border-2 border-dashed p-6 text-center transition ${
            dragActive ? "border-[#4b39db] bg-[#f3f1ff]" : "border-[#d8d3ed] bg-[#faf9ff]"
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
            onChange={(event) => {
              void onFileInputChange(event);
            }}
            disabled={!canUpload || isUploading}
          />
          <p className="text-base font-semibold text-[#2a2640]">
            {isUploading ? "Uploading..." : "Drop a file here or click to select"}
          </p>
          {!canUpload ? (
            <p className="mt-2 text-xs text-[#6e6a86]">Your role can view documents but cannot upload files.</p>
          ) : null}
        </div>

        {feedback ? (
          <p role="status" className={feedbackClasses(feedback.state)}>
            {feedback.message}
            {feedback.requestId ? ` (Trace ID: ${feedback.requestId})` : ""}
          </p>
        ) : null}
      </div>
    </div>
  );
}
