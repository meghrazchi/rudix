"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ChatComposerCommands } from "@/components/chat/ChatComposerCommands";
import { getLocaleDirection } from "@/i18n/direction";
import {
  SourceScopeSelector,
  type SourceScopeMode,
} from "@/components/chat/SourceScopeSelector";

type AnswerLanguageMode =
  | "auto"
  | "same_as_question"
  | "en"
  | "de"
  | "es"
  | "fr";

type ScopeCollection = {
  collection_id: string;
  name: string;
  description: string | null;
};

type ScopeConnectorSource = {
  id: string;
  label: string;
};

type ScopeConnectorConnection = {
  id: string;
  display_name: string;
  provider_key?: string;
  provider_label: string;
  auth_config?: Record<string, unknown>;
  external_account_id: string | null;
  provider?: { display_name: string } | null;
  rootChips?: ScopeConnectorSource[];
};

type ScopeDocument = {
  document_id: string;
  filename: string;
  chunk_count: number;
  updated_at: string | null;
};

type ChatComposerProps = {
  agenticChatEnabled: boolean;
  agenticMode: boolean;
  answerLanguage: AnswerLanguageMode;
  disabled: boolean;
  hasConnectorScopeSelection: boolean;
  hasAvailableDocuments: boolean;
  isCollectionsLoading: boolean;
  isConnectorsLoading: boolean;
  isDocumentsLoading: boolean;
  indexedDocuments: ScopeDocument[];
  totalIndexedDocuments: number;
  maxTopK: number;
  minTopK: number;
  question: string;
  requiresUploadedDocuments: boolean;
  rerank: boolean;
  scopeMode: SourceScopeMode;
  scopeWarning: string | null;
  selectedCollectionIds: string[];
  selectedConnectorConnectionIds: string[];
  selectedProviderSourceIds: string[];
  selectedDocumentIds: string[];
  documentSearchQuery: string;
  collections: ScopeCollection[];
  connectorConnections: ScopeConnectorConnection[];
  onToggleCollection: (collectionId: string) => void;
  onToggleConnectorConnection: (connectionId: string) => void;
  onToggleDocument: (documentId: string) => void;
  onToggleProviderSource: (providerSourceId: string) => void;
  setAgenticMode: (value: boolean) => void;
  setAnswerLanguage: (value: AnswerLanguageMode) => void;
  setDocumentSearchQuery: (value: string) => void;
  setQuestion: (value: string) => void;
  setRerank: (value: boolean) => void;
  setScopeMode: (value: SourceScopeMode) => void;
  setTopK: (value: number) => void;
  submitButtonLabel: string;
  topK: number;
  isGenerating?: boolean;
  onStop?: () => void;
  onSubmit: () => void;
};

const COMPOSER_TEXTAREA_LINE_HEIGHT_PX = 24;
const COMPOSER_TEXTAREA_VERTICAL_PADDING_PX = 24;
const COMPOSER_TEXTAREA_MAX_LINES = 10;

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
  disabled,
  hasConnectorScopeSelection,
  hasAvailableDocuments,
  isCollectionsLoading,
  isConnectorsLoading,
  isDocumentsLoading,
  maxTopK,
  minTopK,
  question,
  requiresUploadedDocuments,
  rerank,
  scopeMode,
  scopeWarning: _scopeWarning,
  selectedCollectionIds,
  selectedConnectorConnectionIds,
  selectedProviderSourceIds,
  selectedDocumentIds,
  documentSearchQuery: _documentSearchQuery,
  setAgenticMode,
  setAnswerLanguage,
  setDocumentSearchQuery: _setDocumentSearchQuery,
  setQuestion,
  setRerank,
  setScopeMode,
  setTopK,
  submitButtonLabel,
  collections,
  connectorConnections,
  indexedDocuments,
  totalIndexedDocuments,
  onToggleCollection,
  onToggleConnectorConnection,
  onToggleDocument,
  onToggleProviderSource,
  topK,
  isGenerating = false,
  onStop,
  onSubmit,
}: ChatComposerProps) {
  const locale = useLocale();
  const localeDirection = getLocaleDirection(locale);
  const t = useTranslations("chat.composer");
  const tPage = useTranslations("chat.page");
  const settingsPanelRef = useRef<HTMLDivElement | null>(null);
  const [isAdditionalSettingsOpen, setIsAdditionalSettingsOpen] =
    useState(false);

  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerHasText = question.trim().length > 0;
  const composerLineCount = Math.max(
    1,
    Math.min(COMPOSER_TEXTAREA_MAX_LINES, question.split(/\r\n|\r|\n/).length),
  );
  const composerSendButtonPositionClass =
    composerLineCount > 1 ? "bottom-2.5" : "top-1/2 -translate-y-1/2";

  const scopeSelectorLabel = useMemo(() => {
    if (scopeMode === "none") {
      return `${t("selectScope")} - ${t("scopeNoRag")}`;
    }
    if (scopeMode === "collection") {
      const label =
        selectedCollectionIds.length > 0
          ? tPage("scopeCollectionsSelected", {
              n: selectedCollectionIds.length,
            })
          : t("scopeCollection");
      return `${t("selectScope")} - ${label}`;
    }
    if (scopeMode === "connectors") {
      const label =
        selectedConnectorConnectionIds.length +
          selectedProviderSourceIds.length >
        0
          ? tPage("connectorSourcesSelected", {
              count:
                selectedConnectorConnectionIds.length +
                selectedProviderSourceIds.length,
            })
          : t("scopeConnectors");
      return `${t("selectScope")} - ${label}`;
    }
    if (scopeMode === "documents") {
      const label =
        selectedDocumentIds.length > 0
          ? tPage("documentsSelected", { count: selectedDocumentIds.length })
          : tPage("selectDocuments");
      return `${t("selectScope")} - ${label}`;
    }
    return `${t("selectScope")} - ${tPage("scopeAllDocuments", { count: totalIndexedDocuments })}`;
  }, [
    selectedCollectionIds.length,
    selectedConnectorConnectionIds.length,
    selectedProviderSourceIds.length,
    selectedDocumentIds.length,
    totalIndexedDocuments,
    scopeMode,
    t,
    tPage,
  ]);

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
    <div
      dir={localeDirection}
      className="shrink-0 border-t border-[#e4e1ee] bg-white p-4 shadow-[0_-18px_42px_rgba(27,27,36,0.04)] lg:p-6"
    >
      <div
        ref={settingsPanelRef}
        className="relative mx-auto max-w-4xl overflow-visible"
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
          className="flex h-full min-h-0 flex-col"
        >
          <div className="relative flex min-h-0 flex-1 flex-col overflow-visible">
            <div className="flex flex-wrap items-center gap-2 pb-3 text-[11px] font-semibold text-[#464555]">
              <SourceScopeSelector
                headingLabel={t("selectScope")}
                triggerLabel={scopeSelectorLabel}
                labels={{
                  triggerAriaLabel: t("scopeAriaLabel"),
                  scopeAllDocuments: t("scopeAllDocuments"),
                  scopeCollection: t("scopeCollection"),
                  scopeConnectors: t("scopeConnectors"),
                  scopeNoRag: t("scopeNoRag"),
                  selectDocuments: tPage("selectDocuments"),
                  documentSearchPlaceholder: tPage("contextSearchPlaceholder"),
                  selectCollections: t("selectCollections"),
                  selectConnectors: t("selectConnectors"),
                  loadingDocuments: tPage("loadingDocuments"),
                  loadingCollections: t("loadingCollections"),
                  loadingConnectors: tPage("loadingConnectors"),
                  noDocumentsAvailable: tPage("noDocumentsAvailable"),
                  noDocumentsMatch: tPage("noDocumentsMatch"),
                  noCollections: tPage("noCollections"),
                  noConnectors: tPage("noConnectors"),
                  documentSelected: tPage("documentSelected"),
                  documentSelect: tPage("documentSelect"),
                  allDocumentsHint: t("scopeAllDocumentsHint"),
                  cancel: tPage("cancel"),
                  apply: tPage("apply"),
                }}
                scopeMode={scopeMode}
                onScopeModeChange={setScopeMode}
                selectedCollectionIds={selectedCollectionIds}
                selectedConnectorConnectionIds={selectedConnectorConnectionIds}
                selectedProviderSourceIds={selectedProviderSourceIds}
                selectedDocumentIds={selectedDocumentIds}
                collections={collections}
                connectorConnections={connectorConnections}
                indexedDocuments={indexedDocuments}
                isCollectionsLoading={isCollectionsLoading}
                isConnectorsLoading={isConnectorsLoading}
                isDocumentsLoading={isDocumentsLoading}
                onToggleCollection={onToggleCollection}
                onToggleConnectorConnection={onToggleConnectorConnection}
                onToggleProviderSource={onToggleProviderSource}
                onToggleDocument={onToggleDocument}
                onDocumentSearchQueryChange={_setDocumentSearchQuery}
                getDocumentSubtitle={(document) =>
                  document.updated_at
                    ? tPage("documentChunks", {
                        count: document.chunk_count,
                        date: document.updated_at,
                      })
                    : `${document.chunk_count} chunks`
                }
              />

              <button
                type="button"
                onClick={() =>
                  setIsAdditionalSettingsOpen((previous) => !previous)
                }
                className="ms-auto inline-flex cursor-pointer items-center gap-2 rounded-xl border border-transparent bg-[#f5f2ff] p-2 text-xs font-bold text-[#777587] transition-all hover:bg-[#e2dfff] hover:text-[#3525cd]"
                aria-expanded={isAdditionalSettingsOpen}
                aria-haspopup="dialog"
                aria-label={t("additionalSettings")}
              >
                <span
                  className="material-symbols-outlined text-[20px]"
                  aria-hidden="true"
                >
                  settings
                </span>
                <span className="sr-only">{t("additionalSettings")}</span>
              </button>
            </div>

            {isAdditionalSettingsOpen && (
              <ChatComposerCommands
                topK={topK}
                minTopK={minTopK}
                maxTopK={maxTopK}
                setTopK={setTopK}
                answerLanguage={answerLanguage}
                setAnswerLanguage={setAnswerLanguage}
                rerank={rerank}
                setRerank={setRerank}
                agenticChatEnabled={agenticChatEnabled}
                agenticMode={agenticMode}
                setAgenticMode={setAgenticMode}
                hasConnectorScopeSelection={hasConnectorScopeSelection}
              />
            )}

            <div className="relative flex min-h-0 flex-1 items-end rounded-2xl border border-[#c7c4d8] bg-white p-2 shadow-sm transition-all focus-within:border-transparent focus-within:ring-2 focus-within:ring-[#3525cd]">
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
                placeholder={t("placeholder")}
                disabled={requiresUploadedDocuments && !hasAvailableDocuments}
                lang={locale}
                dir={question.trim() ? "auto" : localeDirection}
                className={`rudix-chat-scrollbar w-full resize-none overflow-hidden border-none bg-transparent py-3 text-start text-sm text-[#2f2a46] outline-none [unicode-bidi:plaintext] placeholder:text-start placeholder:text-[#777587] focus:ring-0 ${
                  localeDirection === "rtl" ? "pr-4 pl-16" : "pr-16 pl-4"
                }`}
              />
              <div
                className={`absolute end-4 ${composerSendButtonPositionClass} transition-all`}
              >
                {isGenerating ? (
                  <button
                    type="button"
                    onClick={onStop}
                    aria-label={t("stopGenerating")}
                    className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#3525cd] text-white shadow-lg shadow-[#3525cd]/20 transition-all hover:-translate-y-0.5 hover:bg-[#2b1fa8] hover:shadow-[#3525cd]/30 active:translate-y-0 active:scale-95"
                  >
                    <span
                      className="material-symbols-outlined text-[20px]"
                      aria-hidden="true"
                    >
                      stop
                    </span>
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={disabled}
                    aria-label={submitButtonLabel}
                    className={`flex h-10 w-10 items-center justify-center rounded-xl bg-[#3525cd] text-white shadow-lg shadow-[#3525cd]/20 transition-all hover:-translate-y-0.5 hover:shadow-[#3525cd]/30 active:translate-y-0 active:scale-95 disabled:cursor-not-allowed disabled:opacity-60 ${
                      composerHasText ? "opacity-100" : "opacity-0"
                    }`}
                  >
                    <span
                      className="rtl-mirror material-symbols-outlined text-[20px]"
                      aria-hidden="true"
                    >
                      arrow_forward
                    </span>
                  </button>
                )}
              </div>
            </div>
          </div>
        </form>
      </div>

      {!agenticChatEnabled && (
        <p className="mt-2 text-xs text-[#8a4762]">{t("agenticDisabled")}</p>
      )}
      <p className="mt-3 text-center text-[10px] font-medium tracking-wide text-[#777587] uppercase">
        {hasAvailableDocuments || !requiresUploadedDocuments ? (
          t("disclaimer")
        ) : (
          <>
            <span>{t("chatDisabled")}</span>{" "}
            <span>{t("chatDisabledHint")}</span>
          </>
        )}
      </p>
    </div>
  );
}
