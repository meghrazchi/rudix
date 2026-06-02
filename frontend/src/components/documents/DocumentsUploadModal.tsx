"use client";

import {
  useCallback,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";

import { useOverlayFocus } from "@/lib/use-overlay-focus";
import type { CollectionListItemResponse } from "@/lib/api/collections";
import type { UploadDocumentMetadata } from "@/lib/api/documents";
import {
  UPLOAD_LANGUAGES,
  UPLOAD_RETENTION_CLASSES,
} from "@/lib/api/documents";

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
  | "queued_duplicate"
  | "success"
  | "failed"
  | "canceled";

export type UploadProgressItem = {
  fileName: string;
  state: UploadProgressItemState;
  message?: string | null;
  requestId?: string | null;
  canRetry?: boolean;
};

export type UploadProgressState = {
  total: number;
  completed: number;
  currentFileName: string | null;
  items: UploadProgressItem[];
};

export type UploadBatchRecord = {
  id: string;
  startedAt: string;
  total: number;
  succeeded: number;
  failed: number;
  canceled: number;
  files: string[];
};

type DocumentsUploadModalProps = {
  isOpen: boolean;
  canUpload: boolean;
  isUploading: boolean;
  acceptedTypesLabel: string;
  collections: CollectionListItemResponse[];
  onRequestClose: () => void;
  onCancelAll: () => void;
  onCancelItem: (index: number) => void;
  onRetryItem: (index: number) => void;
  onFilesSelected: (
    files: File[],
    metadata: UploadDocumentMetadata,
  ) => Promise<void>;
  feedback: UploadFeedbackState | null;
  progress: UploadProgressState | null;
  uploadHistory: UploadBatchRecord[];
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
  if (state === "queued_duplicate") {
    return "bg-amber-100 text-amber-800";
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

const EMPTY_METADATA: UploadDocumentMetadata = {
  collection_id: null,
  source: null,
  language: null,
  retention_class: null,
  notes: null,
  tags: [],
};

export function DocumentsUploadModal({
  isOpen,
  canUpload,
  isUploading,
  acceptedTypesLabel,
  collections,
  onRequestClose,
  onCancelAll,
  onCancelItem,
  onRetryItem,
  onFilesSelected,
  feedback,
  progress,
  uploadHistory,
}: DocumentsUploadModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [metaOpen, setMetaOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [collectionId, setCollectionId] = useState("");
  const [source, setSource] = useState("");
  const [language, setLanguage] = useState("");
  const [retentionClass, setRetentionClass] = useState("");
  const [notes, setNotes] = useState("");
  const [tagsInput, setTagsInput] = useState("");

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

  function buildMetadata(): UploadDocumentMetadata {
    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    return {
      collection_id: collectionId || null,
      source: source.trim() || null,
      language: language || null,
      retention_class: retentionClass || null,
      notes: notes.trim() || null,
      tags,
    };
  }

  async function handleFileUpload(files: File[]) {
    if (files.length === 0) {
      return;
    }
    await onFilesSelected(files, buildMetadata());
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

  const hasHistory = uploadHistory.length > 0;
  const activeUploads =
    progress?.items.filter(
      (i) => i.state === "pending" || i.state === "uploading",
    ).length ?? 0;

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
        className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[#e5e3f1] bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#e5e3f1] px-6 py-4">
          <div>
            <h3
              id="documents-upload-modal-title"
              className="text-xl font-bold text-[#1b1b24]"
            >
              Upload Center
            </h3>
            <p
              id="documents-upload-modal-description"
              className="text-sm text-[#68647b]"
            >
              Drop files or click to select. Supported: {acceptedTypesLabel}.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {hasHistory && (
              <button
                type="button"
                onClick={() => setHistoryOpen((v) => !v)}
                aria-label="Upload history"
                title="Upload history"
                className={`rounded-full p-1.5 text-[#6f6b86] transition-colors hover:bg-[#f1eff9] hover:text-[#1b1b24] ${historyOpen ? "bg-[#f1eff9] text-[#1b1b24]" : ""}`}
              >
                <span
                  className="material-symbols-outlined text-[20px]"
                  aria-hidden="true"
                >
                  history
                </span>
              </button>
            )}
            <button
              type="button"
              data-overlay-autofocus="true"
              onClick={handleClose}
              aria-label="Close upload center"
              className="rounded-full p-1 text-[#6f6b86] transition-colors hover:bg-[#f1eff9] hover:text-[#1b1b24]"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {/* Upload history panel */}
          {historyOpen && hasHistory && (
            <div className="border-b border-[#e5e3f1] bg-[#fcfbff] px-6 py-4">
              <h4 className="mb-3 text-xs font-bold tracking-[0.08em] text-[#6a6780] uppercase">
                Upload History (this session)
              </h4>
              <ul className="space-y-2">
                {uploadHistory.map((batch) => (
                  <li
                    key={batch.id}
                    className="rounded-lg border border-[#e5e3f1] bg-white px-3 py-2 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[#68647b]">
                        {new Date(batch.startedAt).toLocaleTimeString()} —{" "}
                        {batch.total} file{batch.total !== 1 ? "s" : ""}
                      </span>
                      <div className="flex gap-2">
                        {batch.succeeded > 0 && (
                          <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800">
                            {batch.succeeded} ok
                          </span>
                        )}
                        {batch.failed > 0 && (
                          <span className="rounded-full bg-rose-100 px-2 py-0.5 font-semibold text-rose-800">
                            {batch.failed} failed
                          </span>
                        )}
                        {batch.canceled > 0 && (
                          <span className="rounded-full bg-slate-200 px-2 py-0.5 font-semibold text-slate-700">
                            {batch.canceled} canceled
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="mt-0.5 truncate text-[#9993b8]">
                      {batch.files.join(", ")}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="space-y-5 p-6">
            {/* Drop zone */}
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
                  ? "Uploads are running. You can cancel individual files below."
                  : "PDF, DOCX, TXT · max 25 MB per file"}
              </p>
              {!canUpload ? (
                <p className="mt-2 text-xs text-[#6e6a86]">
                  Your role can view documents but cannot upload files.
                </p>
              ) : null}
            </div>

            {/* Metadata fields */}
            <div className="rounded-xl border border-[#e5e3f1]">
              <button
                type="button"
                onClick={() => setMetaOpen((v) => !v)}
                aria-expanded={metaOpen}
                aria-label="Upload details (optional)"
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-[#3525cd] hover:bg-[#faf9ff]"
              >
                <span className="flex items-center gap-1.5">
                  <span
                    className="material-symbols-outlined text-[18px]"
                    aria-hidden="true"
                  >
                    tune
                  </span>
                  Upload details (optional)
                </span>
                <span
                  className="material-symbols-outlined text-[18px] text-[#9993b8]"
                  aria-hidden="true"
                >
                  {metaOpen ? "expand_less" : "expand_more"}
                </span>
              </button>

              {metaOpen && (
                <div className="grid grid-cols-1 gap-3 border-t border-[#e5e3f1] p-4 sm:grid-cols-2">
                  {/* Collection */}
                  {collections.length > 0 && (
                    <div className="sm:col-span-2">
                      <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                        Collection
                      </label>
                      <select
                        value={collectionId}
                        onChange={(e) => setCollectionId(e.target.value)}
                        className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        disabled={isUploading}
                      >
                        <option value="">— No collection —</option>
                        {collections.map((c) => (
                          <option key={c.collection_id} value={c.collection_id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Tags */}
                  <div className="sm:col-span-2">
                    <label
                      htmlFor="upload-tags"
                      className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase"
                    >
                      Tags
                      <span className="ml-1 font-normal text-[#9993b8] normal-case">
                        (comma-separated)
                      </span>
                    </label>
                    <input
                      id="upload-tags"
                      type="text"
                      value={tagsInput}
                      onChange={(e) => setTagsInput(e.target.value)}
                      placeholder="compliance, legal, 2026"
                      className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
                      disabled={isUploading}
                    />
                  </div>

                  {/* Source */}
                  <div>
                    <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      Source
                    </label>
                    <input
                      type="text"
                      value={source}
                      onChange={(e) => setSource(e.target.value)}
                      placeholder="https://example.com/doc"
                      maxLength={512}
                      className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
                      disabled={isUploading}
                    />
                  </div>

                  {/* Language */}
                  <div>
                    <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      Language
                    </label>
                    <select
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                      disabled={isUploading}
                    >
                      <option value="">— Detect automatically —</option>
                      {UPLOAD_LANGUAGES.map((l) => (
                        <option key={l.code} value={l.code}>
                          {l.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Retention class */}
                  <div>
                    <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      Retention class
                    </label>
                    <select
                      value={retentionClass}
                      onChange={(e) => setRetentionClass(e.target.value)}
                      className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                      disabled={isUploading}
                    >
                      <option value="">— Default —</option>
                      {UPLOAD_RETENTION_CLASSES.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Notes */}
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      Notes
                    </label>
                    <textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="Internal notes about this upload batch…"
                      maxLength={4096}
                      rows={2}
                      className="w-full resize-none rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
                      disabled={isUploading}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* File type badges when idle */}
            {(!progress || progress.total === 0) && (
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
            )}
          </div>

          {/* Upload queue */}
          {progress && progress.total > 0 && (
            <div className="space-y-3 border-t border-[#e5e3f1] px-6 py-5">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-xs font-bold tracking-[0.08em] text-[#6a6780] uppercase">
                  Queue ({activeUploads} active)
                </h4>
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold text-[#4d4870]">
                    {progress.completed}/{progress.total} done
                  </span>
                  {activeUploads > 0 && canUpload && (
                    <button
                      type="button"
                      onClick={onCancelAll}
                      className="text-xs font-semibold text-rose-600 hover:text-rose-800"
                    >
                      Cancel all
                    </button>
                  )}
                </div>
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
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#3525cd]/10">
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
                            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${progressStateClass(item.state)}`}
                          >
                            {item.state === "queued"
                              ? "queued for indexing"
                              : item.state === "queued_duplicate"
                                ? "duplicate — queued"
                                : item.state}
                          </span>
                        </div>
                        {item.state === "uploading" ? (
                          <p className="text-[11px] text-[#4b39db]">
                            Uploading…
                          </p>
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
                      <div className="flex shrink-0 items-center gap-1">
                        {item.state === "failed" &&
                          item.canRetry &&
                          canUpload && (
                            <button
                              type="button"
                              onClick={() => onRetryItem(index)}
                              aria-label={`Retry upload for ${item.fileName}`}
                              title="Retry upload"
                              className="rounded p-1 text-[#3525cd] transition-colors hover:bg-[#3525cd]/10"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                refresh
                              </span>
                            </button>
                          )}
                        {(item.state === "pending" ||
                          item.state === "uploading") &&
                        canUpload ? (
                          <button
                            type="button"
                            onClick={() => onCancelItem(index)}
                            aria-label={`Cancel upload for ${item.fileName}`}
                            className="rounded p-1 text-[#777587] transition-colors hover:text-[#ba1a1a]"
                          >
                            <span className="material-symbols-outlined text-[18px]">
                              cancel
                            </span>
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {feedback ? (
            <p
              role="status"
              className={`${feedbackClasses(feedback.state)} mx-6 mb-5`}
            >
              {feedback.message}
              {feedback.requestId ? ` (Trace ID: ${feedback.requestId})` : ""}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
