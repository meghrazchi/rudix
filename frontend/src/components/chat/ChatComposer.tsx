"use client";

import { useLayoutEffect, useRef } from "react";

import type { CollectionListItemResponse } from "@/lib/api/collections";

type ChatScopeMode = "all" | "collection" | "documents" | "connectors" | "none";
type AnswerLanguageMode =
  | "auto"
  | "same_as_question"
  | "en"
  | "de"
  | "es"
  | "fr";

type ChatComposerProps = {
  agenticChatEnabled: boolean;
  agenticMode: boolean;
  answerLanguage: AnswerLanguageMode;
  collections: CollectionListItemResponse[];
  contextScopeItemCount: number;
  contextScopeLabel: string;
  disabled: boolean;
  filteredSelectedDocumentIds: string[];
  hasConnectorScopeSelection: boolean;
  hasIndexedDocuments: boolean;
  maxTopK: number;
  minTopK: number;
  question: string;
  requiresUploadedDocuments: boolean;
  rerank: boolean;
  scopeMode: ChatScopeMode;
  scopeWarning: string | null;
  selectedCollectionId: string | null;
  selectedConnectorConnectionIds: string[];
  selectedProviderSourceIds: string[];
  setAgenticMode: (value: boolean) => void;
  setAnswerLanguage: (value: AnswerLanguageMode) => void;
  setContextPage: (value: number) => void;
  setContextSearchQuery: (value: string) => void;
  setIsContextModalOpen: (value: boolean) => void;
  setQuestion: (value: string) => void;
  setRerank: (value: boolean) => void;
  setScopeMode: (value: ChatScopeMode) => void;
  setSelectedCollectionId: (value: string | null) => void;
  setTopK: (value: number) => void;
  submitButtonLabel: string;
  topK: number;
  onSubmit: () => void;
};

const COMPOSER_TEXTAREA_LINE_HEIGHT_PX = 24;
const COMPOSER_TEXTAREA_VERTICAL_PADDING_PX = 24;
const COMPOSER_TEXTAREA_MAX_LINES = 10;

const ANSWER_LANGUAGE_OPTIONS: ReadonlyArray<{
  value: AnswerLanguageMode;
  label: string;
}> = [
  { value: "auto", label: "Auto" },
  { value: "same_as_question", label: "Match question" },
  { value: "en", label: "English" },
  { value: "de", label: "German" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
];

function getComposerTextareaHeight(value: string): number {
  const lineCount = Math.max(
    1,
    Math.min(COMPOSER_TEXTAREA_MAX_LINES, value.split(/\r\n|\r|\n/).length),
  );
  return (
    lineCount * COMPOSER_TEXTAREA_LINE_HEIGHT_PX +
    COMPOSER_TEXTAREA_VERTICAL_PADDING_PX
  );
}

export function ChatComposer({
  agenticChatEnabled,
  agenticMode,
  answerLanguage,
  collections,
  contextScopeItemCount,
  contextScopeLabel,
  disabled,
  filteredSelectedDocumentIds,
  hasConnectorScopeSelection,
  hasIndexedDocuments,
  maxTopK,
  minTopK,
  question,
  requiresUploadedDocuments,
  rerank,
  scopeMode,
  scopeWarning,
  selectedCollectionId,
  selectedConnectorConnectionIds,
  selectedProviderSourceIds,
  setAgenticMode,
  setAnswerLanguage,
  setContextPage,
  setContextSearchQuery,
  setIsContextModalOpen,
  setQuestion,
  setRerank,
  setScopeMode,
  setSelectedCollectionId,
  setTopK,
  submitButtonLabel,
  topK,
  onSubmit,
}: ChatComposerProps) {
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerHasText = question.trim().length > 0;
  const composerLineCount = Math.max(
    1,
    Math.min(COMPOSER_TEXTAREA_MAX_LINES, question.split(/\r\n|\r|\n/).length),
  );
  const composerSendButtonPositionClass =
    composerLineCount > 1 ? "bottom-2.5" : "top-1/2 -translate-y-1/2";

  useLayoutEffect(() => {
    const textarea = composerTextareaRef.current;
    if (!textarea) {
      return;
    }

    const nextHeight = getComposerTextareaHeight(question);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY =
      question.split(/\r\n|\r|\n/).length >= COMPOSER_TEXTAREA_MAX_LINES
        ? "auto"
        : "hidden";
  }, [question]);

  return (
    <div className="border-t border-[#e2dff1] p-4">
      <div className="overflow-hidden rounded-2xl border border-[#c7c4d8] bg-[#f0ecf9] shadow-sm">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
          className="flex h-full min-h-0 flex-col"
        >
          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex items-center gap-3 border-b border-[#c7c4d8] bg-[#f5f2ff] px-3 py-2 text-[11px] font-semibold text-[#464555]">
              <div className="flex items-center gap-2">
                <span
                  className="material-symbols-outlined text-[14px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  travel_explore
                </span>
                <span className="tracking-wider uppercase">Scope</span>
                <select
                  value={scopeMode}
                  onChange={(event) =>
                    setScopeMode(event.target.value as ChatScopeMode)
                  }
                  aria-label="Scope type"
                  className="cursor-pointer rounded border border-[#c7c4d8] bg-[#f0ecf9] px-1.5 py-0.5 text-[11px] font-semibold text-[#3525cd] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                >
                  <option value="all">All files</option>
                  <option value="collection">Collection</option>
                  <option value="documents">Files</option>
                  <option value="connectors">Connectors</option>
                  <option value="none">No RAG</option>
                </select>
              </div>

              {scopeMode === "collection" && (
                <>
                  <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />
                  <select
                    value={selectedCollectionId ?? ""}
                    onChange={(event) =>
                      setSelectedCollectionId(event.target.value || null)
                    }
                    aria-label="Select collection"
                    className="max-w-[160px] cursor-pointer rounded border border-[#c7c4d8] bg-[#f0ecf9] px-1.5 py-0.5 text-[11px] font-medium text-[#2a2640] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                  >
                    <option value="">— choose collection —</option>
                    {collections.map((collection) => (
                      <option
                        key={collection.collection_id}
                        value={collection.collection_id}
                      >
                        {collection.name}
                      </option>
                    ))}
                  </select>
                </>
              )}

              {scopeMode === "documents" && (
                <>
                  <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />
                  <button
                    type="button"
                    onClick={() => {
                      setIsContextModalOpen(true);
                      setContextSearchQuery("");
                      setContextPage(1);
                    }}
                    className="flex items-center gap-1 rounded border border-[#c7c4d8] bg-[#f0ecf9] px-1.5 py-0.5 text-[11px] font-medium text-[#464555] transition-colors hover:bg-[#e8e4f8]"
                  >
                    <span
                      className="material-symbols-outlined text-[13px]"
                      aria-hidden="true"
                    >
                      upload_file
                    </span>
                    Select Files
                  </button>
                  {filteredSelectedDocumentIds.length > 0 && (
                    <span className="rounded-full bg-[#ece8ff] px-1.5 py-0.5 text-[10px] font-bold text-[#3525cd]">
                      {filteredSelectedDocumentIds.length} file
                      {filteredSelectedDocumentIds.length !== 1 ? "s" : ""}{" "}
                      selected
                    </span>
                  )}
                </>
              )}

              {scopeMode === "connectors" && (
                <>
                  <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />
                  <button
                    type="button"
                    onClick={() => {
                      setIsContextModalOpen(true);
                      setContextSearchQuery("");
                      setContextPage(1);
                    }}
                    className="flex items-center gap-1 rounded border border-[#c7c4d8] bg-[#f0ecf9] px-1.5 py-0.5 text-[11px] font-medium text-[#464555] transition-colors hover:bg-[#e8e4f8]"
                  >
                    <span
                      className="material-symbols-outlined text-[13px]"
                      aria-hidden="true"
                    >
                      hub
                    </span>
                    Select Sources
                  </button>
                  {hasConnectorScopeSelection && (
                    <span className="rounded-full bg-[#ece8ff] px-1.5 py-0.5 text-[10px] font-bold text-[#3525cd]">
                      {selectedConnectorConnectionIds.length +
                        selectedProviderSourceIds.length}{" "}
                      source
                      {selectedConnectorConnectionIds.length +
                        selectedProviderSourceIds.length !==
                      1
                        ? "s"
                        : ""}{" "}
                      selected
                    </span>
                  )}
                </>
              )}

              <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />

              <div className="flex items-center gap-2">
                <label
                  htmlFor="top-k-slider"
                  className="tracking-wider uppercase"
                >
                  Top-k
                </label>
                <input
                  id="top-k-slider"
                  type="range"
                  min={minTopK}
                  max={maxTopK}
                  value={topK}
                  onChange={(event) => {
                    const parsed = Number.parseInt(event.target.value, 10);
                    if (Number.isFinite(parsed)) {
                      setTopK(Math.min(maxTopK, Math.max(minTopK, parsed)));
                    }
                  }}
                  className="h-1 w-20 cursor-pointer appearance-none rounded-full bg-[#c7c4d8] accent-[#3525cd]"
                />
                <span className="font-mono text-[#3525cd]">{topK}</span>
                <input
                  id="top-k-input"
                  type="number"
                  min={minTopK}
                  max={maxTopK}
                  value={topK}
                  onChange={(event) => {
                    const parsed = Number.parseInt(event.target.value, 10);
                    if (Number.isFinite(parsed)) {
                      setTopK(Math.min(maxTopK, Math.max(minTopK, parsed)));
                    }
                  }}
                  className="sr-only"
                  aria-label="Top K"
                />
              </div>

              <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />

              <div className="flex items-center gap-2">
                <span
                  className="material-symbols-outlined text-[14px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  translate
                </span>
                <span className="tracking-wider uppercase">Answer</span>
                <select
                  value={answerLanguage}
                  onChange={(event) =>
                    setAnswerLanguage(event.target.value as AnswerLanguageMode)
                  }
                  aria-label="Answer language"
                  className="cursor-pointer rounded border border-[#c7c4d8] bg-[#f0ecf9] px-1.5 py-0.5 text-[11px] font-semibold text-[#3525cd] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                >
                  {ANSWER_LANGUAGE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />

              <label className="flex cursor-pointer items-center gap-1.5">
                <span>Rerank</span>
                <span className="relative inline-flex items-center">
                  <input
                    type="checkbox"
                    checked={rerank}
                    onChange={(event) => setRerank(event.target.checked)}
                    className="peer sr-only"
                  />
                  <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd]" />
                  <span className="absolute left-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5" />
                </span>
              </label>

              <span className="h-3 w-px bg-[#c7c4d8]" aria-hidden="true" />

              <label className="flex cursor-pointer items-center gap-1.5">
                <span>Agentic</span>
                <span className="relative inline-flex items-center">
                  <input
                    type="checkbox"
                    checked={agenticMode}
                    disabled={!agenticChatEnabled}
                    onChange={(event) => setAgenticMode(event.target.checked)}
                    className="peer sr-only"
                  />
                  <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd] peer-disabled:opacity-50" />
                  <span className="absolute left-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5 peer-disabled:opacity-80" />
                </span>
              </label>

              <button
                type="button"
                onClick={() => {
                  setIsContextModalOpen(true);
                  setContextSearchQuery("");
                  setContextPage(1);
                }}
                className="ml-auto flex items-center gap-1 rounded px-2 py-1 text-[#3525cd] transition-colors hover:bg-[#ece8ff]/60"
                aria-label={`Context (${contextScopeLabel}) — click to view or change`}
              >
                <span
                  className="material-symbols-outlined text-[13px]"
                  aria-hidden="true"
                >
                  history
                </span>
                Context ({contextScopeItemCount})
              </button>
            </div>

            {scopeWarning && (
              <div className="flex items-center gap-2 border-t border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden="true"
                >
                  warning
                </span>
                {scopeWarning}
              </div>
            )}

            <div className="relative flex min-h-0 flex-1 items-end bg-white">
              <textarea
                ref={composerTextareaRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    (event.metaKey || event.ctrlKey) &&
                    event.key === "Enter"
                  ) {
                    event.preventDefault();
                    onSubmit();
                  }
                }}
                rows={1}
                placeholder="Type a message or use '/' for commands..."
                disabled={requiresUploadedDocuments && !hasIndexedDocuments}
                className="w-full resize-none overflow-hidden border-none bg-transparent py-3 pr-14 pl-3 text-sm text-[#2f2a46] outline-none focus:ring-0"
              />
              <div
                className={`absolute right-3 ${composerSendButtonPositionClass} transition-all`}
              >
                <button
                  type="submit"
                  disabled={disabled}
                  aria-label={submitButtonLabel}
                  className={`flex h-10 w-10 items-center justify-center rounded-xl bg-[#3525cd] text-white transition-all hover:shadow-lg active:scale-90 disabled:cursor-not-allowed disabled:opacity-60 ${
                    composerHasText ? "opacity-100" : "opacity-0"
                  }`}
                >
                  <span
                    className="material-symbols-outlined text-[20px]"
                    aria-hidden="true"
                  >
                    arrow_upward
                  </span>
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>

      {!agenticChatEnabled && (
        <p className="mt-2 text-xs text-[#8a4762]">
          Agentic Mode is disabled for this deployment.
        </p>
      )}
      {agenticChatEnabled && hasConnectorScopeSelection && (
        <p className="mt-2 text-xs text-[#8a4762]">
          Agentic Mode switches to standard retrieval when connector sources are
          selected.
        </p>
      )}
      {!hasIndexedDocuments && requiresUploadedDocuments && (
        <p className="mt-2 text-center text-xs text-[#777587]">
          <span>Chat is disabled until at least one document is indexed.</span>{" "}
          <span>Switch to No RAG mode to chat without documents.</span>
        </p>
      )}
    </div>
  );
}
