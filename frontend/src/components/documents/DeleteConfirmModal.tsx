"use client";

import { useEffect, useRef } from "react";

export type DeleteConfirmModalProps = {
  open: boolean;
  filenames: string[];
  onConfirm: () => void;
  onCancel: () => void;
};

export function DeleteConfirmModal({
  open,
  filenames,
  onConfirm,
  onCancel,
}: DeleteConfirmModalProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) {
      cancelRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCancel();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onCancel]);

  if (!open) return null;

  const isBulk = filenames.length > 1;
  const title = isBulk
    ? `Delete ${filenames.length} documents?`
    : "Delete document?";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl ring-1 ring-[#e5e3f1]">
        <div className="flex items-start gap-3 border-b border-[#e5e3f1] px-6 py-4">
          <span className="material-symbols-outlined mt-0.5 text-rose-600">
            warning
          </span>
          <h2
            id="delete-modal-title"
            className="text-base font-semibold text-[#1b1b24]"
          >
            {title}
          </h2>
        </div>

        <div className="px-6 py-4">
          {isBulk ? (
            <p className="text-sm text-[#505f76]">
              You are about to permanently delete{" "}
              <span className="font-semibold text-[#1b1b24]">
                {filenames.length} documents
              </span>
              . This will remove all associated chunks, vectors, stored files,
              and previews. Documents under a legal hold will be skipped.
            </p>
          ) : (
            <p className="text-sm text-[#505f76]">
              You are about to permanently delete{" "}
              <span className="font-semibold text-[#1b1b24]">
                {filenames[0]}
              </span>
              . This will remove all associated chunks, vectors, stored files,
              and previews.
            </p>
          )}
          <p className="mt-3 text-sm font-semibold text-rose-700">
            This action cannot be undone.
          </p>
        </div>

        <div className="flex justify-end gap-3 border-t border-[#e5e3f1] px-6 py-4">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700"
          >
            Delete permanently
          </button>
        </div>
      </div>
    </div>
  );
}
