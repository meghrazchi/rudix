"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { emptyRuleSet } from "@/components/collections/DynamicRuleBuilder";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  extractRequestIdFromError,
  isEndpointNotFoundError,
} from "@/lib/forbidden";

import { SummaryMetrics } from "@/components/collections/CollectionCards";
import { CollectionDetailDrawer } from "@/components/collections/CollectionDetailDrawer";
import {
  CollectionDialog,
  DEFAULT_FORM,
} from "@/components/collections/CollectionDialog";
import { CollectionsGrid } from "@/components/collections/CollectionsGrid";
import { CollectionsToolbar } from "@/components/collections/CollectionsToolbar";
import { useCollectionsPage } from "@/components/collections/useCollectionsPage";

export { AssignCollectionsDialog } from "@/components/collections/AssignCollectionsDialog";

// ── Collections page ─────────────────────────────────────────────────────────

export function CollectionsPage() {
  const ctl = useCollectionsPage();
  const {
    tc,
    capabilities,
    collectionsEnabled,
    selectedCollectionId,
    setSelectedCollectionId,
    dialogMode,
    setDialogMode,
    actionFeedback,
    actionRequestId,
    dialogSaveError,
    setDialogSaveError,
    collectionsQuery,
    allCollections,
    total,
    listForbidden,
    totalDocs,
    indexedDocs,
    restrictedCount,
    createMutation,
    updateMutation,
    handleCreateSave,
    handleEditSave,
    isLoading,
    isError,
    showGrid,
  } = ctl;

  return (
    <>
      <section className="min-h-screen space-y-6 px-4 py-6 lg:px-8 lg:py-8">
        {/* Page header */}
        <section>
          <span className="mb-1 block text-[11px] font-semibold tracking-widest text-[#3525cd] uppercase">
            {tc("eyebrow")}
          </span>
          <h2 className="text-3xl font-bold text-[#1b1b24]">
            {tc("pageTitle")}
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-[#464555]">
            {tc("pageDescription")}
          </p>
        </section>

        {/* Summary metrics */}
        {showGrid && allCollections.length > 0 ? (
          <SummaryMetrics
            total={total}
            totalDocs={totalDocs}
            indexedDocs={indexedDocs}
            restrictedCount={restrictedCount}
          />
        ) : null}

        <CollectionsToolbar ctl={ctl} />

        {/* Feedback banner */}
        {actionFeedback ? (
          <p
            role="status"
            className="rounded-xl border border-[#ddd7f6] bg-[#f3f1ff] px-4 py-2.5 text-sm text-[#3f3778]"
          >
            {actionFeedback}
            {actionRequestId
              ? ` ${tc("traceIdSuffix", { id: actionRequestId })}`
              : ""}
          </p>
        ) : null}

        {/* Error / empty states */}
        {!collectionsEnabled ? (
          <EmptyState
            title={tc("collectionsNotAvailableTitle")}
            description={tc("collectionsNotAvailableDesc")}
          />
        ) : null}
        {isLoading ? (
          <LoadingState title={tc("loadingCollectionsTitle")} />
        ) : null}
        {isError && isEndpointNotFoundError(collectionsQuery.error) ? (
          <EmptyState
            title={tc("apiNotDeployedTitle")}
            description={tc("apiNotDeployedDesc")}
          />
        ) : null}
        {isError &&
        !isEndpointNotFoundError(collectionsQuery.error) &&
        listForbidden ? (
          <ForbiddenState
            compact
            title={tc("listForbiddenTitle")}
            description={tc("listForbiddenDesc")}
            requestId={extractRequestIdFromError(collectionsQuery.error)}
          />
        ) : null}
        {isError &&
        !isEndpointNotFoundError(collectionsQuery.error) &&
        !listForbidden ? (
          <ErrorState
            error={collectionsQuery.error}
            description={getApiErrorMessage(collectionsQuery.error)}
            onRetry={() => void collectionsQuery.refetch()}
          />
        ) : null}

        {/* Collection grid */}
        <CollectionsGrid ctl={ctl} />
      </section>

      {/* Drawer overlay + drawer */}
      {selectedCollectionId ? (
        <>
          <div
            className="fixed inset-0 z-40 bg-[#302f39]/20"
            onClick={() => setSelectedCollectionId(null)}
          />
          <CollectionDetailDrawer
            key={selectedCollectionId}
            collectionId={selectedCollectionId}
            capabilities={capabilities}
            onClose={() => setSelectedCollectionId(null)}
            onEdit={(collection) => {
              setDialogSaveError(null);
              setDialogMode({ mode: "edit", collection });
            }}
          />
        </>
      ) : null}

      {/* Dialogs */}
      {dialogMode === "create" ? (
        <CollectionDialog
          title={tc("dialogTitleNew")}
          initial={DEFAULT_FORM}
          saving={createMutation.isPending}
          saveError={dialogSaveError}
          onSave={handleCreateSave}
          onClose={() => {
            setDialogMode(null);
            setDialogSaveError(null);
          }}
        />
      ) : dialogMode !== null ? (
        <CollectionDialog
          title={tc("dialogTitleEdit")}
          initial={{
            name: dialogMode.collection.name,
            description: dialogMode.collection.description ?? "",
            access_policy: dialogMode.collection.access_policy,
            is_dynamic: dialogMode.collection.is_dynamic,
            rule_schema: dialogMode.collection.rule_schema ?? emptyRuleSet(),
          }}
          saving={updateMutation.isPending}
          saveError={dialogSaveError}
          onSave={handleEditSave}
          onClose={() => {
            setDialogMode(null);
            setDialogSaveError(null);
          }}
        />
      ) : null}
    </>
  );
}
