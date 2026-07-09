"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";

export type SourceScopeMode =
  | "all"
  | "collection"
  | "documents"
  | "connectors"
  | "none";

type RootChip = {
  id: string;
  label: string;
};

type ScopeCollection = {
  collection_id: string;
  name: string;
  description?: string | null;
};

type ScopeDocument = {
  document_id: string;
  filename: string;
  chunk_count: number;
  updated_at?: string | null;
};

type ScopeConnectorConnection = {
  id: string;
  display_name: string;
  provider_key?: string;
  auth_config?: Record<string, unknown>;
  provider?: { display_name: string } | null;
  provider_label?: string;
  rootChips?: RootChip[];
};

type ScopeLabels = {
  triggerAriaLabel: string;
  scopeAllDocuments: string;
  scopeCollection: string;
  scopeConnectors: string;
  scopeNoRag: string;
  selectDocuments: string;
  selectCollections: string;
  selectConnectors: string;
  loadingDocuments: string;
  loadingCollections: string;
  loadingConnectors: string;
  noDocumentsAvailable: string;
  noDocumentsMatch: string;
  noCollections: string;
  noConnectors: string;
  documentSelected: string;
  documentSelect: string;
  allDocumentsHint: string;
  cancel: string;
  apply: string;
};

type SourceScopeSelectorProps = {
  headingLabel: string;
  triggerLabel: string;
  labels: ScopeLabels;
  scopeMode: SourceScopeMode;
  onScopeModeChange: (value: SourceScopeMode) => void;
  selectedCollectionIds: string[];
  selectedConnectorConnectionIds: string[];
  selectedProviderSourceIds: string[];
  selectedDocumentIds: string[];
  collections: ScopeCollection[];
  connectorConnections: ScopeConnectorConnection[];
  indexedDocuments: ScopeDocument[];
  isCollectionsLoading: boolean;
  isConnectorsLoading: boolean;
  isDocumentsLoading: boolean;
  onToggleCollection: (collectionId: string) => void;
  onToggleConnectorConnection: (connectionId: string) => void;
  onToggleProviderSource: (providerSourceId: string) => void;
  onToggleDocument: (documentId: string) => void;
  getDocumentSubtitle?: (document: ScopeDocument) => string;
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

function formatConnectorSourceRoots(
  providerKey: string,
  authConfig: Record<string, unknown>,
): string[] {
  const rawValues =
    providerKey === "confluence"
      ? authConfig.space_keys
      : providerKey === "google_drive"
        ? [
            ...(Array.isArray(authConfig.folder_ids)
              ? authConfig.folder_ids
              : []),
            ...(Array.isArray(authConfig.drive_ids)
              ? authConfig.drive_ids
              : []),
          ]
        : [];

  if (!Array.isArray(rawValues)) {
    return [];
  }

  return rawValues
    .map((value) => String(value).trim())
    .filter((value) => value.length > 0);
}

function buildConnectorRootChips(
  connection: ScopeConnectorConnection,
): RootChip[] {
  if (connection.rootChips) {
    return connection.rootChips;
  }
  if (!connection.provider_key) {
    return [];
  }
  return formatConnectorSourceRoots(
    connection.provider_key,
    connection.auth_config ?? {},
  ).map((root) => ({
    id: `${connection.id}:${root}`,
    label: root,
  }));
}

export function SourceScopeSelector({
  headingLabel,
  triggerLabel,
  labels,
  scopeMode,
  onScopeModeChange,
  selectedCollectionIds,
  selectedConnectorConnectionIds,
  selectedProviderSourceIds,
  selectedDocumentIds,
  collections,
  connectorConnections,
  indexedDocuments,
  isCollectionsLoading,
  isConnectorsLoading,
  isDocumentsLoading,
  onToggleCollection,
  onToggleConnectorConnection,
  onToggleProviderSource,
  onToggleDocument,
  getDocumentSubtitle,
}: SourceScopeSelectorProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [draftScopeMode, setDraftScopeMode] =
    useState<SourceScopeMode>(scopeMode);
  const [activeScopeSubmenu, setActiveScopeSubmenu] = useState<
    "collections" | "connectors" | "documents" | null
  >(null);
  const [documentSearchQuery, setDocumentSearchQuery] = useState("");
  const [collectionSearchQuery, setCollectionSearchQuery] = useState("");
  const [connectorSearchQuery, setConnectorSearchQuery] = useState("");
  const [menuStyle, setMenuStyle] = useState<CSSProperties | undefined>(
    undefined,
  );

  const selectedCollectionCount = selectedCollectionIds.length;
  const selectedConnectorCount = selectedConnectorConnectionIds.length;
  const selectedProviderSourceCount = selectedProviderSourceIds.length;
  const selectedDocumentCount = selectedDocumentIds.length;

  const filteredDocuments = useMemo(() => {
    const query = documentSearchQuery.trim().toLowerCase();
    if (!query) return indexedDocuments;
    return indexedDocuments.filter((document) =>
      document.filename.toLowerCase().includes(query),
    );
  }, [documentSearchQuery, indexedDocuments]);

  const filteredCollections = useMemo(() => {
    const query = collectionSearchQuery.trim().toLowerCase();
    if (!query) return collections;
    return collections.filter((collection) =>
      collection.name.toLowerCase().includes(query),
    );
  }, [collectionSearchQuery, collections]);

  const filteredConnectors = useMemo(() => {
    const query = connectorSearchQuery.trim().toLowerCase();
    if (!query) return connectorConnections;
    return connectorConnections.filter((connection) => {
      const rootLabels = buildConnectorRootChips(connection).map(
        (root) => root.label,
      );
      const providerLabel =
        connection.provider_label ?? connection.provider?.display_name ?? "";
      return (
        connection.display_name.toLowerCase().includes(query) ||
        (connection.provider_key?.toLowerCase().includes(query) ?? false) ||
        providerLabel.toLowerCase().includes(query) ||
        rootLabels.some((label) => label.toLowerCase().includes(query))
      );
    });
  }, [connectorConnections, connectorSearchQuery]);

  const closeMenu = useCallback(() => {
    setIsOpen(false);
    setActiveScopeSubmenu(null);
    setDocumentSearchQuery("");
    setCollectionSearchQuery("");
    setConnectorSearchQuery("");
  }, []);

  const updateMenuStyle = useCallback(() => {
    const triggerRect = triggerRef.current?.getBoundingClientRect();
    if (!triggerRect) return;

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const viewportPadding = 12;
    const preferredWidth = Math.min(
      56 * 16,
      viewportWidth - viewportPadding * 2,
    );
    const minLeft = viewportPadding;
    const maxLeft = Math.max(
      viewportPadding,
      viewportWidth - preferredWidth - viewportPadding,
    );
    const preferredLeft = Math.min(
      Math.max(triggerRect.left, minLeft),
      maxLeft,
    );
    setMenuStyle({
      position: "fixed",
      left: preferredLeft,
      bottom: Math.max(viewportPadding, viewportHeight - triggerRect.top + 12),
      width: preferredWidth,
      maxHeight: Math.max(280, triggerRect.top - viewportPadding * 2),
    });
  }, []);

  useEffect(() => {
    if (!isOpen) return;

    const onPointerDown = (event: PointerEvent) => {
      if (
        menuRef.current &&
        event.target instanceof Node &&
        menuRef.current.contains(event.target)
      ) {
        return;
      }
      closeMenu();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu();
      }
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeMenu, isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    window.addEventListener("resize", updateMenuStyle);
    window.addEventListener("scroll", updateMenuStyle, true);
    return () => {
      window.removeEventListener("resize", updateMenuStyle);
      window.removeEventListener("scroll", updateMenuStyle, true);
    };
  }, [isOpen, updateMenuStyle]);

  return (
    <div ref={menuRef} className="relative">
      <p className="mb-1 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
        {headingLabel}
      </p>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          if (isOpen) {
            setIsOpen(false);
            setMenuStyle(undefined);
          } else {
            updateMenuStyle();
            setIsOpen(true);
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
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label={labels.triggerAriaLabel}
        className={`flex w-full items-center justify-between rounded-t-2xl border px-4 py-3 text-left transition-colors ${
          isOpen
            ? "border-[#3525cd] bg-white"
            : "border-[#d7d4e8] bg-white hover:border-[#3525cd]/50"
        }`}
      >
        <div className="flex min-w-0 items-center gap-3">
          <span className="material-symbols-outlined text-[#3525cd]">
            list_alt
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-[#2a2640]">
              {triggerLabel}
            </p>
            <p className="truncate text-[11px] text-[#68647b]">
              {labels.allDocumentsHint}
            </p>
          </div>
        </div>
        <span
          className={`material-symbols-outlined text-[#3525cd] transition-transform ${
            isOpen ? "rotate-180" : ""
          }`}
        >
          expand_more
        </span>
      </button>

      {isOpen && (
        <div
          style={menuStyle}
          className="z-50 overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
        >
          <div className="flex min-h-[360px]">
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
                <span className="material-symbols-outlined text-[17px]">
                  folder_open
                </span>
                <span className="flex-1">{labels.scopeAllDocuments}</span>
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
                <span className="material-symbols-outlined text-[17px]">
                  description
                </span>
                <span className="flex-1 truncate">
                  {labels.selectDocuments}
                </span>
                <span className="material-symbols-outlined text-[15px] text-[#6a6780]">
                  chevron_right
                </span>
              </button>
              <button
                type="button"
                disabled={isCollectionsLoading && collections.length === 0}
                onClick={() => {
                  if (isCollectionsLoading && collections.length === 0) return;
                  setDraftScopeMode("collection");
                  setActiveScopeSubmenu("collections");
                }}
                className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                  draftScopeMode === "collection" &&
                  !(isCollectionsLoading && collections.length === 0)
                    ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                    : isCollectionsLoading && collections.length === 0
                      ? "cursor-not-allowed text-[#9a96ad] opacity-50"
                      : "text-[#464555] hover:bg-[#ece8ff]/50"
                }`}
              >
                <span className="material-symbols-outlined text-[17px]">
                  folder_special
                </span>
                <span className="flex-1">{labels.selectCollections}</span>
                {!(isCollectionsLoading && collections.length === 0) && (
                  <span className="material-symbols-outlined text-[15px] text-[#6a6780]">
                    chevron_right
                  </span>
                )}
              </button>
              <button
                type="button"
                disabled={
                  isConnectorsLoading && connectorConnections.length === 0
                }
                onClick={() => {
                  if (
                    isConnectorsLoading &&
                    connectorConnections.length === 0
                  ) {
                    return;
                  }
                  setDraftScopeMode("connectors");
                  setActiveScopeSubmenu("connectors");
                }}
                className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors ${
                  draftScopeMode === "connectors" &&
                  !(isConnectorsLoading && connectorConnections.length === 0)
                    ? "border-y border-[#d7d4e8] bg-white font-semibold text-[#3525cd] shadow-sm"
                    : isConnectorsLoading && connectorConnections.length === 0
                      ? "cursor-not-allowed text-[#9a96ad] opacity-50"
                      : "text-[#464555] hover:bg-[#ece8ff]/50"
                }`}
              >
                <span className="material-symbols-outlined text-[17px]">
                  hub
                </span>
                <span className="flex-1">{labels.selectConnectors}</span>
                {!(
                  isConnectorsLoading && connectorConnections.length === 0
                ) && (
                  <span className="material-symbols-outlined text-[15px] text-[#6a6780]">
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
                  <span className="material-symbols-outlined text-[17px]">
                    do_not_disturb_on
                  </span>
                  <span className="flex-1">{labels.scopeNoRag}</span>
                </button>
              </div>
            </div>

            <div className="flex-grow overflow-y-auto p-4">
              {activeScopeSubmenu === "documents" ? (
                <>
                  <div className="relative mb-3">
                    <span className="material-symbols-outlined absolute top-1/2 left-2 -translate-y-1/2 text-xs text-[#6a6780]">
                      search
                    </span>
                    <input
                      type="text"
                      value={documentSearchQuery}
                      onChange={(event) =>
                        setDocumentSearchQuery(event.target.value)
                      }
                      placeholder={labels.selectDocuments}
                      className="h-9 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                    />
                  </div>
                  <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                    {isDocumentsLoading ? (
                      <p className="text-xs text-[#777587]">
                        {labels.loadingDocuments}
                      </p>
                    ) : filteredDocuments.length === 0 ? (
                      <p className="text-xs text-[#777587]">
                        {indexedDocuments.length === 0
                          ? labels.noDocumentsAvailable
                          : labels.noDocumentsMatch}
                      </p>
                    ) : (
                      filteredDocuments.map((document) => {
                        const documentSelected = selectedDocumentIds.includes(
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
                                {getDocumentSubtitle
                                  ? getDocumentSubtitle(document)
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
                                ? labels.documentSelected
                                : labels.documentSelect}
                            </span>
                          </button>
                        );
                      })
                    )}
                  </div>
                </>
              ) : null}

              {activeScopeSubmenu === "collections" ? (
                <>
                  <div className="relative mb-3">
                    <span className="material-symbols-outlined absolute top-1/2 left-2 -translate-y-1/2 text-[14px] text-[#6a6780]">
                      search
                    </span>
                    <input
                      type="text"
                      value={collectionSearchQuery}
                      onChange={(event) =>
                        setCollectionSearchQuery(event.target.value)
                      }
                      placeholder={labels.selectCollections}
                      className="h-9 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                    />
                  </div>
                  <div className="space-y-2">
                    {isCollectionsLoading ? (
                      <p className="text-xs text-[#777587]">
                        {labels.loadingCollections}
                      </p>
                    ) : filteredCollections.length === 0 ? (
                      <p className="text-xs text-[#777587]">
                        {labels.noCollections}
                      </p>
                    ) : (
                      filteredCollections.map((collection, index) => {
                        const isSelected = selectedCollectionIds.includes(
                          collection.collection_id,
                        );
                        const colorClass =
                          COLLECTION_COLORS[index % COLLECTION_COLORS.length];
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
                                onToggleCollection(collection.collection_id)
                              }
                              className="rounded border-[#c7c4d8] text-[#3525cd] focus:ring-[#3525cd]/20"
                            />
                            <span
                              className={`material-symbols-outlined flex-shrink-0 text-[22px] ${colorClass}`}
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
              ) : null}

              {activeScopeSubmenu === "connectors" ? (
                <>
                  <div className="relative mb-3">
                    <span className="material-symbols-outlined absolute top-1/2 left-2 -translate-y-1/2 text-[14px] text-[#6a6780]">
                      search
                    </span>
                    <input
                      type="text"
                      value={connectorSearchQuery}
                      onChange={(event) =>
                        setConnectorSearchQuery(event.target.value)
                      }
                      placeholder={labels.selectConnectors}
                      className="h-9 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                    />
                  </div>
                  <div className="space-y-2">
                    {isConnectorsLoading ? (
                      <p className="text-xs text-[#777587]">
                        {labels.loadingConnectors}
                      </p>
                    ) : filteredConnectors.length === 0 ? (
                      <p className="text-xs text-[#777587]">
                        {labels.noConnectors}
                      </p>
                    ) : (
                      filteredConnectors.map((connection, index) => {
                        const selected =
                          selectedConnectorConnectionIds.includes(
                            connection.id,
                          );
                        const rootChips = buildConnectorRootChips(connection);
                        const sourceCount = rootChips.length;
                        const colorClass =
                          COLLECTION_COLORS[index % COLLECTION_COLORS.length];
                        return (
                          <div
                            key={connection.id}
                            className={`rounded-lg border p-3 transition-colors ${
                              selected
                                ? "border-[#c7c4d8] bg-[#ece8ff]/50"
                                : "border-[#e2dff1] hover:bg-[#f7f5ff]"
                            }`}
                          >
                            <label className="flex cursor-pointer items-center gap-3">
                              <input
                                type="checkbox"
                                checked={selected}
                                onChange={() =>
                                  onToggleConnectorConnection(connection.id)
                                }
                                className="rounded border-[#c7c4d8] text-[#3525cd] focus:ring-[#3525cd]/20"
                              />
                              <span
                                className={`material-symbols-outlined flex-shrink-0 text-[22px] ${colorClass}`}
                              >
                                hub
                              </span>
                              <div className="min-w-0 flex-1">
                                <span className="block truncate text-sm font-bold text-[#2f2a46]">
                                  {connection.display_name}
                                </span>
                                <p className="truncate text-[10px] text-[#6a6780]">
                                  {connection.provider_label ??
                                    connection.provider?.display_name ??
                                    connection.provider_key ??
                                    ""}
                                  {sourceCount > 0
                                    ? ` · ${sourceCount} source${sourceCount === 1 ? "" : "s"}`
                                    : ""}
                                </p>
                              </div>
                            </label>

                            {rootChips.length > 0 ? (
                              <div className="mt-3 flex flex-wrap gap-2 pl-8">
                                {rootChips.map((root) => {
                                  const isRootSelected =
                                    selectedProviderSourceIds.includes(
                                      root.label,
                                    );
                                  return (
                                    <button
                                      key={root.id}
                                      type="button"
                                      onClick={() => {
                                        if (!selected) {
                                          onToggleConnectorConnection(
                                            connection.id,
                                          );
                                        }
                                        onToggleProviderSource(root.label);
                                      }}
                                      className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                                        isRootSelected
                                          ? "border-[#3525cd] bg-[#ece8ff] text-[#3525cd]"
                                          : "border-[#d2cee6] bg-white text-[#5f5a74] hover:border-[#b9b2dd] hover:bg-[#faf9ff]"
                                      }`}
                                    >
                                      {root.label}
                                    </button>
                                  );
                                })}
                              </div>
                            ) : null}
                          </div>
                        );
                      })
                    )}
                  </div>
                </>
              ) : null}

              {activeScopeSubmenu === null ? (
                <div className="flex h-full min-h-[200px] items-center justify-center">
                  <p className="text-center text-sm text-[#9a96ad]">
                    {labels.allDocumentsHint}
                  </p>
                </div>
              ) : null}
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-[#ece8f7] bg-[#f7f5ff] px-4 py-3">
            <button
              type="button"
              onClick={closeMenu}
              className="px-4 py-1.5 text-xs font-semibold text-[#464555] hover:text-[#2f2a46]"
            >
              {labels.cancel}
            </button>
            {(() => {
              const isDisabled =
                (activeScopeSubmenu === "documents" &&
                  selectedDocumentCount === 0) ||
                (activeScopeSubmenu === "connectors" &&
                  selectedConnectorCount === 0 &&
                  selectedProviderSourceCount === 0) ||
                (activeScopeSubmenu === "collections" &&
                  selectedCollectionCount === 0);

              return (
                <button
                  type="button"
                  disabled={isDisabled}
                  onClick={() => {
                    onScopeModeChange(draftScopeMode);
                    closeMenu();
                  }}
                  className="rounded-lg bg-[#3525cd] px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {labels.apply}
                </button>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
