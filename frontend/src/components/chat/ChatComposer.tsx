"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
  setAgenticMode: (value: boolean) => void;
  setAnswerLanguage: (value: AnswerLanguageMode) => void;
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

const COLLECTION_COLORS = [
  "text-indigo-600",
  "text-purple-600",
  "text-blue-600",
  "text-emerald-600",
  "text-amber-500",
  "text-rose-500",
  "text-cyan-600",
  "text-fuchsia-600",
];

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
  documentSearchQuery,
  setAgenticMode,
  setAnswerLanguage,
  setDocumentSearchQuery,
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
  const [draftScopeMode, setDraftScopeMode] =
    useState<ChatScopeMode>(scopeMode);
  const [activeScopeSubmenu, setActiveScopeSubmenu] = useState<
    "collections" | "connectors" | "documents" | null
  >(null);
  const [collectionSearchQuery, setCollectionSearchQuery] = useState("");
  const [connectorSearchQuery, setConnectorSearchQuery] = useState("");

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

  const filteredCollections = useMemo(() => {
    const query = collectionSearchQuery.trim().toLowerCase();
    if (!query) return collections;
    return collections.filter((c) => c.name.toLowerCase().includes(query));
  }, [collectionSearchQuery, collections]);

  const filteredConnectors = useMemo(() => {
    const query = connectorSearchQuery.trim().toLowerCase();
    if (!query) return connectorConnections;
    return connectorConnections.filter(
      (c) =>
        c.display_name.toLowerCase().includes(query) ||
        c.provider_label.toLowerCase().includes(query),
    );
  }, [connectorSearchQuery, connectorConnections]);

  const scopeSelectorLabel = useMemo(() => {
    if (scopeMode === "none") {
      return `${t("selectScope")} - ${t("scopeNoRag")}`;
    }
    if (scopeMode === "collection") {
      const label =
        collectionSelectionCount > 0
          ? tPage("scopeCollectionsSelected", {
              n: collectionSelectionCount,
            })
          : t("scopeCollection");
      return `${t("selectScope")} - ${label}`;
    }
    if (scopeMode === "connectors") {
      const label =
        connectorSelectionCount > 0
          ? tPage("connectorSourcesSelected", {
              count: connectorSelectionCount,
            })
          : t("scopeConnectors");
      return `${t("selectScope")} - ${label}`;
    }
    if (scopeMode === "documents") {
      const label =
        fileSelectionCount > 0
          ? tPage("documentsSelected", { count: fileSelectionCount })
          : tPage("selectDocuments");
      return `${t("selectScope")} - ${label}`;
    }
    return `${t("selectScope")} - ${tPage("scopeAllDocuments", { count: totalIndexedDocuments })}`;
  }, [
    collectionSelectionCount,
    connectorSelectionCount,
    fileSelectionCount,
    totalIndexedDocuments,
    scopeMode,
    t,
    tPage,
  ]);

  const closeScopeMenu = useCallback(() => {
    setIsScopeMenuOpen(false);
    setActiveScopeSubmenu(null);
    setDocumentSearchQuery("");
    setCollectionSearchQuery("");
    setConnectorSearchQuery("");
  }, [setDocumentSearchQuery]);

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
  }, [closeScopeMenu, isAdditionalSettingsOpen, isScopeMenuOpen]);

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
                <button
                  type="button"
                  onClick={() => {
                    setIsScopeMenuOpen((previous) => !previous);
                    if (!isScopeMenuOpen) {
                      setDraftScopeMode(scopeMode);
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
                  className="inline-flex cursor-pointer items-center gap-1 rounded border border-[#c7c4d8] bg-[#f0ecf9] px-2 py-0.5 text-[11px] font-semibold text-[#3525cd] transition-colors outline-none hover:bg-[#ece8ff] focus:ring-1 focus:ring-[#3525cd]/20"
                >
                  <span
                    className="material-symbols-outlined text-[14px]"
                    aria-hidden="true"
                  >
                    filter_list
                  </span>
                  <span className="truncate">{scopeSelectorLabel}</span>
                  <span
                    className="material-symbols-outlined text-[14px]"
                    aria-hidden="true"
                  >
                    expand_more
                  </span>
                </button>
              </div>

              <button
                type="button"
                onClick={() =>
                  setIsAdditionalSettingsOpen((previous) => !previous)
                }
                className="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-full border border-[#c7c4d8] bg-white px-3 py-1 text-[11px] font-semibold text-[#2a2640] transition-colors hover:bg-[#faf9ff]"
                aria-expanded={isAdditionalSettingsOpen}
                aria-haspopup="dialog"
                aria-label={t("additionalSettings")}
              >
                <span
                  className="material-symbols-outlined text-[13px]"
                  aria-hidden="true"
                >
                  settings
                </span>
                {t("additionalSettings")}
              </button>
            </div>

            {isScopeMenuOpen && (
              <div
                ref={scopeMenuRef}
                className="absolute bottom-full left-3 z-40 mb-2 flex w-[min(40rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
                role="menu"
                aria-label={t("scopeAriaLabel")}
              >
                <div className="flex min-h-[360px]">
                  {/* Left category nav */}
                  <div className="flex w-44 flex-shrink-0 flex-col border-r border-[#ece8f7] bg-[#f7f5ff] py-2">
                    <button
                      type="button"
                      onClick={() => {
                        setDraftScopeMode("all");
                        setActiveScopeSubmenu(null);
                      }}
                      className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                        draftScopeMode === "all"
                          ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                          : "text-[#464555] hover:bg-[#ece8ff]/50"
                      }`}
                    >
                      <span
                        className="material-symbols-outlined text-[17px]"
                        aria-hidden="true"
                      >
                        folder_open
                      </span>
                      <span className="flex-1">{t("scopeAllDocuments")}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDraftScopeMode("documents");
                        setActiveScopeSubmenu("documents");
                      }}
                      className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                        draftScopeMode === "documents"
                          ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                          : "text-[#464555] hover:bg-[#ece8ff]/50"
                      }`}
                    >
                      <span
                        className="material-symbols-outlined text-[17px]"
                        aria-hidden="true"
                      >
                        description
                      </span>
                      <span className="flex-1 truncate">
                        {tPage("selectDocuments")}
                      </span>
                      <span
                        className="material-symbols-outlined text-[15px] text-[#6a6780]"
                        aria-hidden="true"
                      >
                        chevron_right
                      </span>
                    </button>
                    <button
                      type="button"
                      disabled={!hasCollectionOptions}
                      onClick={() => {
                        if (!hasCollectionOptions) return;
                        setDraftScopeMode("collection");
                        setActiveScopeSubmenu("collections");
                      }}
                      className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                        draftScopeMode === "collection" && hasCollectionOptions
                          ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                          : hasCollectionOptions
                            ? "text-[#464555] hover:bg-[#ece8ff]/50"
                            : "cursor-not-allowed text-[#9a96ad] opacity-50"
                      }`}
                    >
                      <span
                        className="material-symbols-outlined text-[17px]"
                        aria-hidden="true"
                      >
                        folder_special
                      </span>
                      <span className="flex-1">{t("scopeCollection")}</span>
                      {hasCollectionOptions && (
                        <span
                          className="material-symbols-outlined text-[15px] text-[#6a6780]"
                          aria-hidden="true"
                        >
                          chevron_right
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      disabled={!hasConnectorOptions}
                      onClick={() => {
                        if (!hasConnectorOptions) return;
                        setDraftScopeMode("connectors");
                        setActiveScopeSubmenu("connectors");
                      }}
                      className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                        draftScopeMode === "connectors" && hasConnectorOptions
                          ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                          : hasConnectorOptions
                            ? "text-[#464555] hover:bg-[#ece8ff]/50"
                            : "cursor-not-allowed text-[#9a96ad] opacity-50"
                      }`}
                    >
                      <span
                        className="material-symbols-outlined text-[17px]"
                        aria-hidden="true"
                      >
                        hub
                      </span>
                      <span className="flex-1">{t("scopeConnectors")}</span>
                      {hasConnectorOptions && (
                        <span
                          className="material-symbols-outlined text-[15px] text-[#6a6780]"
                          aria-hidden="true"
                        >
                          chevron_right
                        </span>
                      )}
                    </button>
                    <div className="mt-auto border-t border-[#ece8f7] pt-2">
                      <button
                        type="button"
                        onClick={() => {
                          setDraftScopeMode("none");
                          setActiveScopeSubmenu(null);
                        }}
                        className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                          draftScopeMode === "none"
                            ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                            : "text-[#464555] hover:bg-[#ece8ff]/50"
                        }`}
                      >
                        <span
                          className="material-symbols-outlined text-[17px]"
                          aria-hidden="true"
                        >
                          do_not_disturb_on
                        </span>
                        <span className="flex-1">{t("scopeNoRag")}</span>
                      </button>
                    </div>
                  </div>

                  {/* Right content panel */}
                  <div className="flex-grow overflow-y-auto p-4">
                    {activeScopeSubmenu === "collections" && (
                      <>
                        <div className="relative mb-3">
                          <span
                            className="material-symbols-outlined absolute top-1/2 left-2 -translate-y-1/2 text-[14px] text-[#6a6780]"
                            aria-hidden="true"
                          >
                            search
                          </span>
                          <input
                            type="text"
                            value={collectionSearchQuery}
                            onChange={(event) =>
                              setCollectionSearchQuery(event.target.value)
                            }
                            placeholder={t("selectCollections")}
                            className="h-9 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                          />
                        </div>
                        <div className="space-y-2">
                          {isCollectionsLoading ? (
                            <p className="text-xs text-[#777587]">
                              {t("loadingCollections")}
                            </p>
                          ) : filteredCollections.length === 0 ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("noCollections")}
                            </p>
                          ) : (
                            filteredCollections.map((collection, index) => {
                              const isSelected = selectedCollectionIds.includes(
                                collection.collection_id,
                              );
                              const colorClass =
                                COLLECTION_COLORS[
                                  index % COLLECTION_COLORS.length
                                ];
                              return (
                                <label
                                  key={collection.collection_id}
                                  className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                                    isSelected
                                      ? "border-[#c7c4d8] bg-[#ece8ff]/50"
                                      : "border-[#e2dff1] hover:bg-[#f7f5ff]"
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() =>
                                      onToggleCollection(
                                        collection.collection_id,
                                      )
                                    }
                                    className="rounded border-[#c7c4d8] text-[#3525cd] focus:ring-[#3525cd]/20"
                                  />
                                  <span
                                    className={`material-symbols-outlined flex-shrink-0 text-[22px] ${colorClass}`}
                                    aria-hidden="true"
                                  >
                                    folder_special
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-bold text-[#2f2a46]">
                                      {collection.name}
                                    </span>
                                    {collection.description && (
                                      <p className="truncate text-[10px] text-[#6a6780]">
                                        {collection.description}
                                      </p>
                                    )}
                                  </div>
                                </label>
                              );
                            })
                          )}
                        </div>
                      </>
                    )}

                    {activeScopeSubmenu === "connectors" && (
                      <>
                        <div className="relative mb-3">
                          <span
                            className="material-symbols-outlined absolute top-1/2 left-2 -translate-y-1/2 text-[14px] text-[#6a6780]"
                            aria-hidden="true"
                          >
                            search
                          </span>
                          <input
                            type="text"
                            value={connectorSearchQuery}
                            onChange={(event) =>
                              setConnectorSearchQuery(event.target.value)
                            }
                            placeholder={t("selectConnectors")}
                            className="h-9 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                          />
                        </div>
                        <div className="space-y-2">
                          {isConnectorsLoading ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("loadingConnectors")}
                            </p>
                          ) : filteredConnectors.length === 0 ? (
                            <p className="text-xs text-[#777587]">
                              {tPage("noConnectors")}
                            </p>
                          ) : (
                            filteredConnectors.map((connection, index) => {
                              const isSelected =
                                selectedConnectorConnectionIds.includes(
                                  connection.id,
                                );
                              const colorClass =
                                COLLECTION_COLORS[
                                  index % COLLECTION_COLORS.length
                                ];
                              return (
                                <label
                                  key={connection.id}
                                  className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                                    isSelected
                                      ? "border-[#c7c4d8] bg-[#ece8ff]/50"
                                      : "border-[#e2dff1] hover:bg-[#f7f5ff]"
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() =>
                                      onToggleConnectorConnection(connection.id)
                                    }
                                    className="rounded border-[#c7c4d8] text-[#3525cd] focus:ring-[#3525cd]/20"
                                  />
                                  <span
                                    className={`material-symbols-outlined flex-shrink-0 text-[22px] ${colorClass}`}
                                    aria-hidden="true"
                                  >
                                    hub
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-bold text-[#2f2a46]">
                                      {connection.display_name}
                                    </span>
                                    {connection.provider_label && (
                                      <p className="truncate text-[10px] text-[#6a6780]">
                                        {connection.provider_label}
                                      </p>
                                    )}
                                  </div>
                                </label>
                              );
                            })
                          )}
                        </div>
                      </>
                    )}

                    {activeScopeSubmenu === "documents" && (
                      <>
                        <div className="relative mb-3">
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
                        <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
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
                      </>
                    )}

                    {activeScopeSubmenu === null && (
                      <div className="flex h-full min-h-[200px] items-center justify-center">
                        <p className="text-center text-sm text-[#9a96ad]">
                          All documents are included in this search.
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Bottom action bar */}
                <div className="flex items-center justify-end gap-3 border-t border-[#ece8f7] bg-[#f7f5ff] px-4 py-3">
                  <button
                    type="button"
                    onClick={closeScopeMenu}
                    className="px-4 py-1.5 text-xs font-semibold text-[#464555] hover:text-[#2f2a46]"
                  >
                    {tPage("cancel")}
                  </button>
                  {(() => {
                    const isDisabled =
                      (activeScopeSubmenu === "documents" &&
                        fileSelectionCount === 0) ||
                      (activeScopeSubmenu === "connectors" &&
                        connectorSelectionCount === 0) ||
                      (activeScopeSubmenu === "collections" &&
                        collectionSelectionCount === 0);
                    return (
                      <button
                        type="button"
                        disabled={isDisabled}
                        title={
                          isDisabled
                            ? tPage("applySelectionRequired")
                            : undefined
                        }
                        onClick={() => {
                          setScopeMode(draftScopeMode);
                          closeScopeMenu();
                        }}
                        className="rounded-lg bg-[#3525cd] px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {tPage("apply")}
                      </button>
                    );
                  })()}
                </div>
              </div>
            )}

            {isAdditionalSettingsOpen && (
              <div className="absolute right-3 bottom-full z-30 mb-3 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-[#d7d4e8] bg-white p-3 shadow-2xl">
                <div className="mb-3">
                  <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                    {t("additionalSettingsTitle")}
                  </p>
                  <p className="text-xs text-[#6a6780]">
                    {t("additionalSettingsSubtitle")}
                  </p>
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
