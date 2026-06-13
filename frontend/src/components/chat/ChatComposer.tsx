"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

type ChatScopeMode = "all" | "collection" | "documents" | "connectors" | "none";
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
  provider_label: string;
  external_account_id: string | null;
  rootChips: ScopeConnectorSource[];
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
  contextScopeItemCount: number;
  disabled: boolean;
  hasConnectorScopeSelection: boolean;
  hasAvailableDocuments: boolean;
  isCollectionsLoading: boolean;
  isConnectorsLoading: boolean;
  isDocumentsLoading: boolean;
  indexedDocuments: ScopeDocument[];
  maxTopK: number;
  minTopK: number;
  question: string;
  requiresUploadedDocuments: boolean;
  rerank: boolean;
  scopeMode: ChatScopeMode;
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
  setContextPage: (value: number) => void;
  setContextSearchQuery: (value: string) => void;
  setIsContextModalOpen: (value: boolean) => void;
  setDocumentSearchQuery: (value: string) => void;
  setQuestion: (value: string) => void;
  setRerank: (value: boolean) => void;
  setScopeMode: (value: ChatScopeMode) => void;
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
  contextScopeItemCount,
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
  scopeWarning,
  selectedCollectionIds,
  selectedConnectorConnectionIds,
  selectedProviderSourceIds,
  selectedDocumentIds,
  documentSearchQuery,
  setAgenticMode,
  setAnswerLanguage,
  setContextPage,
  setContextSearchQuery,
  setIsContextModalOpen,
  setDocumentSearchQuery,
  setQuestion,
  setRerank,
  setScopeMode,
  setTopK,
  submitButtonLabel,
  collections,
  connectorConnections,
  indexedDocuments,
  onToggleCollection,
  onToggleConnectorConnection,
  onToggleDocument,
  onToggleProviderSource,
  topK,
  isGenerating = false,
  onStop,
  onSubmit,
}: ChatComposerProps) {
  const t = useTranslations("chat.composer");
  const tPage = useTranslations("chat.page");
  const tLang = useTranslations("languageSwitcher");
  const settingsPanelRef = useRef<HTMLDivElement | null>(null);
  const scopeMenuRef = useRef<HTMLDivElement | null>(null);
  const [isAdditionalSettingsOpen, setIsAdditionalSettingsOpen] =
    useState(false);
  const [isScopeMenuOpen, setIsScopeMenuOpen] = useState(false);
  const [activeScopeSubmenu, setActiveScopeSubmenu] = useState<
    "collections" | "connectors" | "documents" | null
  >(null);

  const answerLanguageOptions: ReadonlyArray<{
    value: AnswerLanguageMode;
    label: string;
  }> = [
    { value: "auto", label: t("answerAuto") },
    { value: "same_as_question", label: t("answerMatchQuestion") },
    { value: "en", label: tLang("en") },
    { value: "de", label: tLang("de") },
    { value: "es", label: tLang("es") },
    { value: "fr", label: tLang("fr") },
  ];

  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerHasText = question.trim().length > 0;
  const composerLineCount = Math.max(
    1,
    Math.min(COMPOSER_TEXTAREA_MAX_LINES, question.split(/\r\n|\r|\n/).length),
  );
  const composerSendButtonPositionClass =
    composerLineCount > 1 ? "bottom-2.5" : "top-1/2 -translate-y-1/2";

  const collectionSelectionCount = selectedCollectionIds.length;
  const connectorSelectionCount =
    selectedConnectorConnectionIds.length + selectedProviderSourceIds.length;
  const fileSelectionCount = selectedDocumentIds.length;
  const hasCollectionOptions = isCollectionsLoading || collections.length > 0;
  const hasConnectorOptions =
    isConnectorsLoading || connectorConnections.length > 0;
  const filteredDocuments = useMemo(() => {
    const query = documentSearchQuery.trim().toLowerCase();
    if (!query) {
      return indexedDocuments;
    }
    return indexedDocuments.filter((document) =>
      document.filename.toLowerCase().includes(query),
    );
  }, [documentSearchQuery, indexedDocuments]);

  const scopeSummaryLabel = useMemo(() => {
    if (scopeMode === "none") {
      return t("scopeNoRag");
    }
    if (scopeMode === "collection") {
      return collectionSelectionCount > 0
        ? tPage("scopeCollectionsSelected", {
            n: collectionSelectionCount,
          })
        : t("scopeCollection");
    }
    if (scopeMode === "connectors") {
      return connectorSelectionCount > 0
        ? tPage("connectorSourcesSelected", {
            count: connectorSelectionCount,
          })
        : t("scopeConnectors");
    }
    if (scopeMode === "documents") {
      return fileSelectionCount > 0
        ? tPage("documentsSelected", { count: fileSelectionCount })
        : tPage("selectDocuments");
    }
    return fileSelectionCount > 0
      ? tPage("scopeAllDocumentsSelected", { n: fileSelectionCount })
      : tPage("scopeAllDocuments", { count: contextScopeItemCount });
  }, [
    collectionSelectionCount,
    connectorSelectionCount,
    fileSelectionCount,
    contextScopeItemCount,
    scopeMode,
    t,
    tPage,
  ]);

  function closeScopeMenu() {
    setIsScopeMenuOpen(false);
    setActiveScopeSubmenu(null);
    setDocumentSearchQuery("");
  }

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

  useEffect(() => {
    if (!isAdditionalSettingsOpen && !isScopeMenuOpen) {
      return;
    }

    const onPointerDown = (event: MouseEvent | PointerEvent) => {
      if (
        settingsPanelRef.current &&
        !settingsPanelRef.current.contains(event.target as Node)
      ) {
        setIsAdditionalSettingsOpen(false);
        closeScopeMenu();
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsAdditionalSettingsOpen(false);
        closeScopeMenu();
      }
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isAdditionalSettingsOpen, isScopeMenuOpen]);

  return (
    <div className="border-t border-[#e2dff1] p-4">
      <div
        ref={settingsPanelRef}
        className="relative overflow-visible rounded-2xl border border-[#c7c4d8] bg-[#f0ecf9] shadow-sm"
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
          className="flex h-full min-h-0 flex-col"
        >
          <div className="relative flex min-h-0 flex-1 flex-col overflow-visible">
            <div className="flex flex-wrap items-center gap-2 border-b border-[#c7c4d8] bg-[#f5f2ff] px-3 py-2 text-[11px] font-semibold text-[#464555]">
              <div className="flex items-center gap-2">
                <span
                  className="material-symbols-outlined text-[14px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  travel_explore
                </span>
                <span className="tracking-wider uppercase">
                  {t("scopeLabel")}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setIsScopeMenuOpen((previous) => !previous);
                    if (!isScopeMenuOpen) {
                      setActiveScopeSubmenu(
                        scopeMode === "collection"
                          ? "collections"
                          : scopeMode === "connectors"
                            ? "connectors"
                            : scopeMode === "documents"
                              ? "documents"
                              : null,
                      );
                    }
                  }}
                  aria-expanded={isScopeMenuOpen}
                  aria-haspopup="menu"
                  aria-label={t("scopeAriaLabel")}
                  className="inline-flex items-center gap-1 rounded border border-[#c7c4d8] bg-[#f0ecf9] px-2 py-0.5 text-[11px] font-semibold text-[#3525cd] transition-colors outline-none hover:bg-[#ece8ff] focus:ring-1 focus:ring-[#3525cd]/20"
                >
                  <span className="truncate">{scopeSummaryLabel}</span>
                  <span
                    className="material-symbols-outlined text-[14px]"
                    aria-hidden="true"
                  >
                    expand_more
                  </span>
                </button>
              </div>

              {scopeMode === "collection" && collectionSelectionCount > 0 && (
                <span className="rounded-full bg-[#ece8ff] px-1.5 py-0.5 text-[10px] font-bold text-[#3525cd]">
                  {tPage("collectionsSelected", {
                    n: collectionSelectionCount,
                  })}
                </span>
              )}

              {scopeMode === "connectors" && hasConnectorScopeSelection && (
                <span className="rounded-full bg-[#ece8ff] px-1.5 py-0.5 text-[10px] font-bold text-[#3525cd]">
                  {tPage("connectorSourcesSelected", {
                    count: connectorSelectionCount,
                  })}
                </span>
              )}

              {scopeMode === "documents" && fileSelectionCount > 0 && (
                <span className="rounded-full bg-[#ece8ff] px-1.5 py-0.5 text-[10px] font-bold text-[#3525cd]">
                  {tPage("documentsSelected", { count: fileSelectionCount })}
                </span>
              )}

              <button
                type="button"
                onClick={() => {
                  setIsContextModalOpen(true);
                  setContextSearchQuery("");
                  setContextPage(1);
                }}
                className="flex items-center gap-1 rounded border border-[#c7c4d8] bg-[#f0ecf9] px-2 py-0.5 text-[11px] font-medium text-[#464555] transition-colors hover:bg-[#e8e4f8]"
              >
                <span
                  className="material-symbols-outlined text-[13px]"
                  aria-hidden="true"
                >
                  history
                </span>
                {t("contextButton", { count: contextScopeItemCount })}
              </button>

              <button
                type="button"
                onClick={() =>
                  setIsAdditionalSettingsOpen((previous) => !previous)
                }
                className="ml-auto inline-flex items-center gap-1 rounded-full border border-[#c7c4d8] bg-white px-3 py-1 text-[11px] font-semibold text-[#2a2640] transition-colors hover:bg-[#faf9ff]"
                aria-expanded={isAdditionalSettingsOpen}
                aria-haspopup="dialog"
                aria-label={t("additionalSettings")}
              >
                <span
                  className="material-symbols-outlined text-[13px]"
                  aria-hidden="true"
                >
                  tune
                </span>
                {t("additionalSettings")}
              </button>
            </div>

            {isScopeMenuOpen && (
              <div
                ref={scopeMenuRef}
                className="absolute bottom-full left-3 z-40 mb-2 w-[min(20rem,calc(100vw-1.5rem))] rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
                role="menu"
                aria-label={t("scopeAriaLabel")}
              >
                <div className="p-2">
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => {
                        setScopeMode("all");
                        setActiveScopeSubmenu("documents");
                      }}
                      onMouseEnter={() => setActiveScopeSubmenu("documents")}
                      className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition-colors ${
                        scopeMode === "all"
                          ? "bg-[#ece8ff] text-[#3525cd]"
                          : "text-[#2f2a46] hover:bg-[#f7f5ff]"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className="material-symbols-outlined text-[18px]"
                          aria-hidden="true"
                        >
                          folder_open
                        </span>
                        <span>{t("scopeAllDocuments")}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="text-[10px] font-semibold text-[#6a6780]">
                          {fileSelectionCount > 0
                            ? tPage("documentsSelected", {
                                count: fileSelectionCount,
                              })
                            : tPage("selectDocuments")}
                        </span>
                        <span
                          className="material-symbols-outlined text-[16px] text-[#6a6780]"
                          aria-hidden="true"
                        >
                          chevron_right
                        </span>
                      </span>
                    </button>
                    {activeScopeSubmenu === "documents" && (
                      <div className="absolute top-0 left-full ml-2 w-72 rounded-2xl border border-[#d7d4e8] bg-white p-3 shadow-2xl">
                        <div className="relative mb-2">
                          <span
                            className="material-symbols-outlined absolute top-1/2 left-2 -translate-y-1/2 text-xs text-[#6a6780]"
                            aria-hidden="true"
                          >
                            search
                          </span>
                          <input
                            type="text"
                            value={documentSearchQuery}
                            onChange={(event) =>
                              setDocumentSearchQuery(event.target.value)
                            }
                            placeholder={tPage("contextSearchPlaceholder")}
                            className="h-9 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                          />
                        </div>
                        <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                          {isDocumentsLoading ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("loadingDocuments")}
                            </p>
                          ) : filteredDocuments.length === 0 ? (
                            <p className="text-xs text-[#777587]">
                              {indexedDocuments.length === 0
                                ? tPage("noDocumentsAvailable")
                                : tPage("noDocumentsMatch")}
                            </p>
                          ) : (
                            filteredDocuments.map((document) => {
                              const documentSelected =
                                selectedDocumentIds.includes(
                                  document.document_id,
                                );
                              return (
                                <button
                                  key={document.document_id}
                                  type="button"
                                  onClick={() =>
                                    onToggleDocument(document.document_id)
                                  }
                                  className={`flex w-full items-start justify-between gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${
                                    documentSelected
                                      ? "border-[#3525cd] bg-[#ece8ff]"
                                      : "border-[#e2dff1] bg-[#faf9ff] hover:bg-white"
                                  }`}
                                >
                                  <span className="min-w-0">
                                    <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                                      {document.filename}
                                    </span>
                                    <span className="mt-1 block text-[11px] text-[#6a6780]">
                                      {document.updated_at
                                        ? tPage("documentChunks", {
                                            count: document.chunk_count,
                                            date: document.updated_at,
                                          })
                                        : `${document.chunk_count} chunks`}
                                    </span>
                                  </span>
                                  <span
                                    className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
                                      documentSelected
                                        ? "bg-[#ece8ff] text-[#3525cd]"
                                        : "bg-[#f1f0f5] text-[#6a6780]"
                                    }`}
                                  >
                                    {documentSelected
                                      ? tPage("documentSelected")
                                      : tPage("documentSelect")}
                                  </span>
                                </button>
                              );
                            })
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="relative">
                    <button
                      type="button"
                      disabled={!hasCollectionOptions}
                      onClick={() => {
                        if (!hasCollectionOptions) {
                          return;
                        }
                        setScopeMode("collection");
                        setActiveScopeSubmenu("collections");
                      }}
                      onMouseEnter={() => {
                        if (hasCollectionOptions) {
                          setActiveScopeSubmenu("collections");
                        }
                      }}
                      className={`mt-1 flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition-colors ${
                        scopeMode === "collection"
                          ? "bg-[#ece8ff] text-[#3525cd]"
                          : hasCollectionOptions
                            ? "text-[#2f2a46] hover:bg-[#f7f5ff]"
                            : "cursor-not-allowed text-[#9a96ad] opacity-60"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className="material-symbols-outlined text-[18px]"
                          aria-hidden="true"
                        >
                          folder
                        </span>
                        <span>{t("scopeCollection")}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="text-[10px] font-semibold text-[#6a6780]">
                          {collectionSelectionCount > 0
                            ? tPage("collectionsSelected", {
                                n: collectionSelectionCount,
                              })
                            : tPage("collectionsTitle")}
                        </span>
                        <span
                          className="material-symbols-outlined text-[16px] text-[#6a6780]"
                          aria-hidden="true"
                        >
                          chevron_right
                        </span>
                      </span>
                    </button>
                    {activeScopeSubmenu === "collections" && (
                      <div className="absolute top-0 left-full ml-2 w-64 rounded-2xl border border-[#d7d4e8] bg-white p-3 shadow-2xl">
                        <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                          {isCollectionsLoading ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("loadingCollections")}
                            </p>
                          ) : collections.length === 0 ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("noCollections")}
                            </p>
                          ) : (
                            collections.map((collection) => {
                              const collectionSelected =
                                selectedCollectionIds.includes(
                                  collection.collection_id,
                                );
                              return (
                                <button
                                  key={collection.collection_id}
                                  type="button"
                                  onClick={() =>
                                    onToggleCollection(collection.collection_id)
                                  }
                                  className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${
                                    collectionSelected
                                      ? "border-[#3525cd] bg-[#ece8ff]"
                                      : "border-[#e2dff1] bg-[#faf9ff] hover:bg-white"
                                  }`}
                                >
                                  <span className="min-w-0 truncate text-sm font-semibold text-[#2f2a46]">
                                    {collection.name}
                                  </span>
                                </button>
                              );
                            })
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="relative">
                    <button
                      type="button"
                      disabled={!hasConnectorOptions}
                      onClick={() => {
                        if (!hasConnectorOptions) {
                          return;
                        }
                        setScopeMode("connectors");
                        setActiveScopeSubmenu("connectors");
                      }}
                      onMouseEnter={() => {
                        if (hasConnectorOptions) {
                          setActiveScopeSubmenu("connectors");
                        }
                      }}
                      className={`mt-1 flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition-colors ${
                        scopeMode === "connectors"
                          ? "bg-[#ece8ff] text-[#3525cd]"
                          : hasConnectorOptions
                            ? "text-[#2f2a46] hover:bg-[#f7f5ff]"
                            : "cursor-not-allowed text-[#9a96ad] opacity-60"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className="material-symbols-outlined text-[18px]"
                          aria-hidden="true"
                        >
                          hub
                        </span>
                        <span>{t("scopeConnectors")}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="text-[10px] font-semibold text-[#6a6780]">
                          {connectorSelectionCount > 0
                            ? tPage("connectorSourcesSelected", {
                                count: connectorSelectionCount,
                              })
                            : tPage("connectorSourcesTitle")}
                        </span>
                        <span
                          className="material-symbols-outlined text-[16px] text-[#6a6780]"
                          aria-hidden="true"
                        >
                          chevron_right
                        </span>
                      </span>
                    </button>
                    {activeScopeSubmenu === "connectors" && (
                      <div className="absolute top-0 left-full ml-2 w-[18rem] rounded-2xl border border-[#d7d4e8] bg-white p-3 shadow-2xl">
                        <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                          {isConnectorsLoading ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("loadingConnectors")}
                            </p>
                          ) : connectorConnections.length === 0 ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("noConnectors")}
                            </p>
                          ) : (
                            connectorConnections.map((connection) => {
                              const connectionSelected =
                                selectedConnectorConnectionIds.includes(
                                  connection.id,
                                );
                              return (
                                <div
                                  key={connection.id}
                                  className="rounded-xl border border-[#e2dff1] bg-[#faf9ff] p-3"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        onToggleConnectorConnection(
                                          connection.id,
                                        )
                                      }
                                      className={`flex min-w-0 flex-1 items-center gap-2 text-left transition-colors ${
                                        connectionSelected
                                          ? "text-[#3525cd]"
                                          : "text-[#2f2a46]"
                                      }`}
                                    >
                                      <span
                                        className={`material-symbols-outlined text-[18px] ${connectionSelected ? "text-[#3525cd]" : "text-[#6a6780]"}`}
                                        aria-hidden="true"
                                      >
                                        hub
                                      </span>
                                      <span className="min-w-0 truncate text-sm font-semibold">
                                        {connection.display_name}
                                      </span>
                                    </button>
                                  </div>
                                  {connection.rootChips.length > 0 ? (
                                    <div className="mt-2 flex flex-wrap gap-2">
                                      {connection.rootChips.map((root) => {
                                        const selected =
                                          selectedProviderSourceIds.includes(
                                            root.label,
                                          );
                                        return (
                                          <button
                                            key={root.id}
                                            type="button"
                                            onClick={() => {
                                              if (!connectionSelected) {
                                                onToggleConnectorConnection(
                                                  connection.id,
                                                );
                                              }
                                              onToggleProviderSource(
                                                root.label,
                                              );
                                            }}
                                            className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                                              selected
                                                ? "border-[#3525cd] bg-[#ece8ff] text-[#3525cd]"
                                                : "border-[#d2cee6] bg-[#faf9ff] text-[#5f5a74] hover:border-[#b9b2dd] hover:bg-white"
                                            }`}
                                          >
                                            {root.label}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  ) : (
                                    <p className="mt-2 text-xs text-[#777587]">
                                      {tPage("useConnectionForAll")}
                                    </p>
                                  )}
                                </div>
                              );
                            })
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="mt-1 border-t border-[#ece8f7] pt-1">
                    <button
                      type="button"
                      onClick={() => {
                        setScopeMode("none");
                        closeScopeMenu();
                      }}
                      className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition-colors ${
                        scopeMode === "none"
                          ? "bg-[#ece8ff] text-[#3525cd]"
                          : "text-[#2f2a46] hover:bg-[#f7f5ff]"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className="material-symbols-outlined text-[18px]"
                          aria-hidden="true"
                        >
                          do_not_disturb_on
                        </span>
                        <span>{t("scopeNoRag")}</span>
                      </span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {isAdditionalSettingsOpen && (
              <div className="absolute right-3 bottom-full z-30 mb-3 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-[#d7d4e8] bg-white p-3 shadow-2xl">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                      {t("additionalSettingsTitle")}
                    </p>
                    <p className="text-xs text-[#6a6780]">
                      {t("additionalSettingsSubtitle")}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsAdditionalSettingsOpen(false)}
                    className="rounded-lg border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
                  >
                    {t("close")}
                  </button>
                </div>
                <div className="flex flex-col gap-3">
                  <div className="rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <label
                        htmlFor="top-k-slider"
                        className="text-[10px] font-bold tracking-widest text-[#464555] uppercase"
                      >
                        {t("topKLabel")}
                      </label>
                      <span className="font-mono text-xs text-[#3525cd]">
                        {topK}
                      </span>
                    </div>
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
                      className="h-1 w-full cursor-pointer appearance-none rounded-full bg-[#c7c4d8] accent-[#3525cd]"
                    />
                  </div>

                  <div className="rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
                    <label
                      htmlFor="answer-language"
                      className="mb-2 block text-[10px] font-bold tracking-widest text-[#464555] uppercase"
                    >
                      {t("answerLabel")}
                    </label>
                    <select
                      id="answer-language"
                      value={answerLanguage}
                      onChange={(event) =>
                        setAnswerLanguage(
                          event.target.value as AnswerLanguageMode,
                        )
                      }
                      aria-label={t("answerLanguageAriaLabel")}
                      className="w-full cursor-pointer rounded-lg border border-[#d2cee6] bg-white px-2 py-2 text-sm font-semibold text-[#3525cd] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                    >
                      {answerLanguageOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <label className="flex items-center justify-between rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
                    <span>
                      <span className="block text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                        {t("rerankLabel")}
                      </span>
                      <span className="block text-xs text-[#6a6780]">
                        {t("rerankDescription")}
                      </span>
                    </span>
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

                  <label className="flex items-center justify-between rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
                    <span>
                      <span className="block text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                        {t("agenticLabel")}
                      </span>
                      <span className="block text-xs text-[#6a6780]">
                        {agenticChatEnabled
                          ? t("agenticDescription")
                          : t("agenticDisabled")}
                      </span>
                    </span>
                    <span className="relative inline-flex items-center">
                      <input
                        type="checkbox"
                        checked={agenticMode}
                        disabled={!agenticChatEnabled}
                        onChange={(event) =>
                          setAgenticMode(event.target.checked)
                        }
                        className="peer sr-only"
                      />
                      <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd] peer-disabled:opacity-50" />
                      <span className="absolute left-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5 peer-disabled:opacity-80" />
                    </span>
                  </label>
                </div>
                {agenticChatEnabled && hasConnectorScopeSelection ? (
                  <p className="mt-3 text-xs text-[#8a4762]">
                    {t("agenticConnectorWarning")}
                  </p>
                ) : null}
              </div>
            )}

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
                placeholder={t("placeholder")}
                disabled={requiresUploadedDocuments && !hasAvailableDocuments}
                className="w-full resize-none overflow-hidden border-none bg-transparent py-3 pr-14 pl-3 text-sm text-[#2f2a46] outline-none focus:ring-0"
              />
              <div
                className={`absolute right-3 ${composerSendButtonPositionClass} transition-all`}
              >
                {isGenerating ? (
                  <button
                    type="button"
                    onClick={onStop}
                    aria-label={t("stopGenerating")}
                    className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#3525cd] text-white transition-all hover:bg-[#2b1fa8] hover:shadow-lg active:scale-90"
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
                )}
              </div>
            </div>
          </div>
        </form>
      </div>

      {!agenticChatEnabled && (
        <p className="mt-2 text-xs text-[#8a4762]">{t("agenticDisabled")}</p>
      )}
      {!hasAvailableDocuments && requiresUploadedDocuments && (
        <p className="mt-2 text-center text-xs text-[#777587]">
          <span>{t("chatDisabled")}</span> <span>{t("chatDisabledHint")}</span>
        </p>
      )}
    </div>
  );
}
