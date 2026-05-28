import type { FormEvent, RefObject } from "react";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type { DocumentListResponse } from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";

type CreateSetDialogProps = {
  containerRef?: RefObject<HTMLDivElement | null>;
  isOpen: boolean;
  isSubmitting: boolean;
  name: string;
  description: string;
  error: string | null;
  onNameChange: (next: string) => void;
  onDescriptionChange: (next: string) => void;
  onClose: () => void;
  onSubmit: () => void;
};

export function CreateEvaluationSetDialog({
  containerRef,
  isOpen,
  isSubmitting,
  name,
  description,
  error,
  onNameChange,
  onDescriptionChange,
  onClose,
  onSubmit,
}: CreateSetDialogProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-[#16162c]/55 px-4"
      onClick={onClose}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-evaluation-set-title"
        className="w-full max-w-lg rounded-2xl border border-[#d8d4e8] bg-white p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <div>
            <h2
              id="create-evaluation-set-title"
              className="text-lg font-semibold text-[#292442]"
            >
              Create evaluation set
            </h2>
            <p className="mt-1 text-sm text-[#67627f]">
              Add a dataset for evaluation questions before starting runs.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded border border-[#cbc6dd] px-2 py-1 text-xs font-semibold text-[#423d5f] disabled:cursor-not-allowed disabled:opacity-60"
          >
            Close
          </button>
        </div>

        <form
          className="space-y-3"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <label className="grid gap-1">
            <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
              Set name
            </span>
            <input
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder="Regression suite"
              className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
            />
          </label>

          <label className="grid gap-1">
            <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
              Description
            </span>
            <textarea
              value={description}
              onChange={(event) => onDescriptionChange(event.target.value)}
              placeholder="Optional context for this evaluation dataset"
              rows={3}
              className="rounded-lg border border-[#d1cce4] px-2 py-1.5 text-sm text-[#2a2640]"
            />
          </label>

          {error ? <p className="text-xs text-rose-700">{error}</p> : null}

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded border border-[#cbc6dd] px-3 py-1.5 text-sm font-semibold text-[#423d5f] disabled:cursor-not-allowed disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2c1ea9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? "Creating..." : "Create set"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

type StartRunDialogProps = {
  containerRef?: RefObject<HTMLDivElement | null>;
  isOpen: boolean;
  isSubmitting: boolean;
  setName: string;
  topK: number;
  rerank: boolean;
  modelName: string;
  metricOptions: string;
  selectedDocumentIds: string[];
  indexedDocuments: DocumentListResponse["items"];
  isDocumentsLoading: boolean;
  documentsError: unknown;
  error: string | null;
  onClose: () => void;
  onSubmit: () => void;
  onTopKChange: (next: number) => void;
  onRerankChange: (next: boolean) => void;
  onModelNameChange: (next: string) => void;
  onMetricOptionsChange: (next: string) => void;
  onToggleDocument: (documentId: string) => void;
};

export function StartEvaluationRunDialog({
  containerRef,
  isOpen,
  isSubmitting,
  setName,
  topK,
  rerank,
  modelName,
  metricOptions,
  selectedDocumentIds,
  indexedDocuments,
  isDocumentsLoading,
  documentsError,
  error,
  onClose,
  onSubmit,
  onTopKChange,
  onRerankChange,
  onModelNameChange,
  onMetricOptionsChange,
  onToggleDocument,
}: StartRunDialogProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-[#16162c]/55 px-4"
      onClick={onClose}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-evaluation-run-title"
        className="w-full max-w-2xl rounded-2xl border border-[#d8d4e8] bg-white p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <div>
            <h2
              id="start-evaluation-run-title"
              className="text-lg font-semibold text-[#292442]"
            >
              Start evaluation run
            </h2>
            <p className="mt-1 text-sm text-[#67627f]">
              Queue a run for{" "}
              <span className="font-semibold text-[#2a2640]">{setName}</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded border border-[#cbc6dd] px-2 py-1 text-xs font-semibold text-[#423d5f] disabled:cursor-not-allowed disabled:opacity-60"
          >
            Close
          </button>
        </div>

        <form
          className="space-y-3"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="grid gap-1">
              <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                Top K
              </span>
              <input
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(event) => {
                  const parsed = Number.parseInt(event.target.value, 10);
                  if (Number.isFinite(parsed)) {
                    onTopKChange(parsed);
                  }
                }}
                className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
              />
            </label>

            <label className="grid gap-1">
              <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                Model override
              </span>
              <input
                value={modelName}
                onChange={(event) => onModelNameChange(event.target.value)}
                placeholder="Optional backend model"
                className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
              />
            </label>
          </div>

          <label className="flex items-start gap-2 rounded-lg border border-[#ded9ec] bg-[#fcfbff] p-3 text-sm text-[#3e3a59]">
            <input
              type="checkbox"
              checked={rerank}
              onChange={(event) => onRerankChange(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              Enable rerank
              <span className="mt-1 block text-xs text-[#6d6983]">
                Apply a second-pass ranking stage before generation.
              </span>
            </span>
          </label>

          <label className="grid gap-1">
            <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
              Metric options JSON
            </span>
            <textarea
              value={metricOptions}
              onChange={(event) => onMetricOptionsChange(event.target.value)}
              rows={3}
              placeholder='{"faithfulness":true,"answer_relevance":true}'
              className="rounded-lg border border-[#d1cce4] px-2 py-1.5 text-sm text-[#2a2640]"
            />
          </label>

          <div>
            <p className="mb-1 text-xs font-semibold tracking-wide text-[#65617b] uppercase">
              Scope to indexed documents
            </p>
            {isDocumentsLoading ? (
              <LoadingState compact title="Loading indexed documents..." />
            ) : documentsError ? (
              <ErrorState
                compact
                error={documentsError}
                description={getApiErrorMessage(documentsError)}
              />
            ) : indexedDocuments.length === 0 ? (
              <EmptyState compact title="No indexed documents available." />
            ) : (
              <ul className="max-h-40 space-y-1 overflow-auto rounded-lg border border-[#e6e2f2] bg-[#fcfbff] p-2">
                {indexedDocuments.map((document) => (
                  <li key={document.document_id}>
                    <label className="flex items-center gap-2 text-xs text-[#35314f]">
                      <input
                        type="checkbox"
                        checked={selectedDocumentIds.includes(
                          document.document_id,
                        )}
                        onChange={() => onToggleDocument(document.document_id)}
                      />
                      <span className="truncate" title={document.filename}>
                        {document.filename}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {error ? <p className="text-xs text-rose-700">{error}</p> : null}

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded border border-[#cbc6dd] px-3 py-1.5 text-sm font-semibold text-[#423d5f] disabled:cursor-not-allowed disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2c1ea9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? "Queueing..." : "Queue run"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
