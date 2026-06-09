import type { FormEvent, RefObject } from "react";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type { ChunkingProfile } from "@/lib/schemas/chunking-profiles";
import type { DocumentListResponse } from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import type { ModelProfileResponse } from "@/lib/api/model-profiles";

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
  chunkingProfiles: ChunkingProfile[];
  isChunkingProfilesLoading: boolean;
  chunkingProfilesError: unknown;
  selectedChunkingProfileIds: string[];
  regressionThresholds: {
    retrievalHitRateMin: string;
    citationAccuracyScoreMin: string;
    faithfulnessScoreMin: string;
    maxNotFoundRate: string;
  };
  indexedDocuments: DocumentListResponse["items"];
  isDocumentsLoading: boolean;
  documentsError: unknown;
  modelProfiles: ModelProfileResponse[];
  isModelProfilesLoading: boolean;
  modelProfilesError: unknown;
  selectedModelProfileId: string;
  error: string | null;
  onClose: () => void;
  onSubmit: () => void;
  onTopKChange: (next: number) => void;
  onRerankChange: (next: boolean) => void;
  onModelNameChange: (next: string) => void;
  onMetricOptionsChange: (next: string) => void;
  onToggleDocument: (documentId: string) => void;
  onToggleChunkingProfile: (profileId: string) => void;
  onModelProfileChange: (profileId: string) => void;
  onRegressionThresholdChange: (
    key:
      | "retrievalHitRateMin"
      | "citationAccuracyScoreMin"
      | "faithfulnessScoreMin"
      | "maxNotFoundRate",
    value: string,
  ) => void;
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
  chunkingProfiles,
  isChunkingProfilesLoading,
  chunkingProfilesError,
  selectedChunkingProfileIds,
  regressionThresholds,
  indexedDocuments,
  isDocumentsLoading,
  documentsError,
  modelProfiles,
  isModelProfilesLoading,
  modelProfilesError,
  selectedModelProfileId,
  error,
  onClose,
  onSubmit,
  onTopKChange,
  onRerankChange,
  onModelNameChange,
  onMetricOptionsChange,
  onToggleDocument,
  onToggleChunkingProfile,
  onModelProfileChange,
  onRegressionThresholdChange,
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

          <div className="space-y-2 rounded-lg border border-[#e6e2f2] bg-[#fcfbff] p-3">
            <div>
              <p className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                Model profile
              </p>
              <p className="mt-1 text-xs text-[#6d6983]">
                Select a saved model profile to benchmark. Leave unset to use
                the org&apos;s default evaluations profile.
              </p>
            </div>
            {isModelProfilesLoading ? (
              <LoadingState compact title="Loading model profiles..." />
            ) : modelProfilesError ? (
              <ErrorState
                compact
                error={modelProfilesError}
                description={getApiErrorMessage(modelProfilesError)}
              />
            ) : (
              <select
                value={selectedModelProfileId}
                onChange={(event) => onModelProfileChange(event.target.value)}
                className="h-9 w-full rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640] bg-white"
              >
                <option value="">Org default (evaluations profile)</option>
                {modelProfiles.map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>
                    {profile.profile_name} — {profile.provider_type}/
                    {profile.base_model}
                    {profile.is_experimental ? " (experimental)" : ""}
                  </option>
                ))}
              </select>
            )}
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

          <div className="space-y-2 rounded-lg border border-[#e6e2f2] bg-[#fcfbff] p-3">
            <div>
              <p className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                Chunking profiles
              </p>
              <p className="mt-1 text-xs text-[#6d6983]">
                Leave all profiles unselected to evaluate the current live
                index. Select one profile to pin the run. Select multiple
                profiles to compare strategies on the same dataset.
              </p>
            </div>

            {isChunkingProfilesLoading ? (
              <LoadingState compact title="Loading chunking profiles..." />
            ) : chunkingProfilesError ? (
              <ErrorState
                compact
                error={chunkingProfilesError}
                description={getApiErrorMessage(chunkingProfilesError)}
              />
            ) : chunkingProfiles.length === 0 ? (
              <EmptyState
                compact
                title="No saved chunking profiles."
                description="The run will use the current indexed corpus unless you create profiles first."
              />
            ) : (
              <ul className="max-h-40 space-y-1 overflow-auto rounded-lg border border-[#e6e2f2] bg-white p-2">
                {chunkingProfiles.map((profile) => (
                  <li key={profile.profile_id}>
                    <label className="flex items-start gap-2 text-xs text-[#35314f]">
                      <input
                        type="checkbox"
                        checked={selectedChunkingProfileIds.includes(
                          profile.profile_id,
                        )}
                        onChange={() =>
                          onToggleChunkingProfile(profile.profile_id)
                        }
                      />
                      <span>
                        <span className="font-semibold">{profile.name}</span>
                        <span className="ml-1 text-[#6d6983]">
                          ({profile.config.strategy})
                        </span>
                        {profile.is_default ? (
                          <span className="ml-1 rounded-full border border-[#d7d2e8] bg-[#f4f1ff] px-1.5 py-0.5 text-[10px] font-semibold text-[#4d3fd1]">
                            Default
                          </span>
                        ) : null}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="space-y-2 rounded-lg border border-[#e6e2f2] bg-[#fcfbff] p-3">
            <div>
              <p className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                Regression thresholds
              </p>
              <p className="mt-1 text-xs text-[#6d6983]">
                Optional release gates. Any configured threshold can flag a
                comparison target as regressed.
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="grid gap-1">
                <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                  Min retrieval hit rate
                </span>
                <input
                  value={regressionThresholds.retrievalHitRateMin}
                  onChange={(event) =>
                    onRegressionThresholdChange(
                      "retrievalHitRateMin",
                      event.target.value,
                    )
                  }
                  placeholder="0.70"
                  inputMode="decimal"
                  className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
                />
              </label>

              <label className="grid gap-1">
                <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                  Min citation accuracy
                </span>
                <input
                  value={regressionThresholds.citationAccuracyScoreMin}
                  onChange={(event) =>
                    onRegressionThresholdChange(
                      "citationAccuracyScoreMin",
                      event.target.value,
                    )
                  }
                  placeholder="0.80"
                  inputMode="decimal"
                  className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
                />
              </label>

              <label className="grid gap-1">
                <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                  Min faithfulness
                </span>
                <input
                  value={regressionThresholds.faithfulnessScoreMin}
                  onChange={(event) =>
                    onRegressionThresholdChange(
                      "faithfulnessScoreMin",
                      event.target.value,
                    )
                  }
                  placeholder="0.80"
                  inputMode="decimal"
                  className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
                />
              </label>

              <label className="grid gap-1">
                <span className="text-xs font-semibold tracking-wide text-[#65617b] uppercase">
                  Max not-found rate
                </span>
                <input
                  value={regressionThresholds.maxNotFoundRate}
                  onChange={(event) =>
                    onRegressionThresholdChange(
                      "maxNotFoundRate",
                      event.target.value,
                    )
                  }
                  placeholder="0.20"
                  inputMode="decimal"
                  className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
                />
              </label>
            </div>
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
