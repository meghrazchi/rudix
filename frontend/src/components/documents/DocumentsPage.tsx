"use client";

import { DocumentsUploadModal } from "@/components/documents/DocumentsUploadModal";
import { DeleteConfirmModal } from "@/components/documents/DeleteConfirmModal";
import { ACCEPTED_UPLOAD_TYPES_LABEL } from "@/components/documents/upload-validation";
import { AssignCollectionsDialog } from "@/components/collections/CollectionsPage";
import { DocumentsActivityCards } from "@/components/documents/list/DocumentsActivityCards";
import { DocumentsListSection } from "@/components/documents/list/DocumentsListSection";
import { DocumentsUploadOverview } from "@/components/documents/list/DocumentsUploadOverview";
import { SelectedDocumentPanel } from "@/components/documents/list/SelectedDocumentPanel";
import { useDocumentsPage } from "@/components/documents/list/useDocumentsPage";

export function DocumentsPage() {
  const ctl = useDocumentsPage();
  const {
    isUploadModalOpen,
    uploadFeedback,
    uploadProgress,
    isUploading,
    uploadHistory,
    cancelUploadAtIndex,
    cancelAllUploads,
    handleUploadModalClose,
    handleFileUpload,
    handleRetryItem,
    assignDocumentId,
    setAssignDocumentId,
    assignDocumentName,
    setAssignDocumentName,
    assignSaveError,
    setAssignSaveError,
    uploadCollections,
    assignCollections,
    docCollectionsQuery,
    assignCollectionsMutation,
    capabilities,
    selectedIds,
    deleteModalState,
    setDeleteModalState,
    deleteMutation,
    bulkDeleteMutation,
  } = ctl;

  return (
    <section className="space-y-6 bg-white px-4 py-5 lg:px-8 lg:py-8">
      <DocumentsUploadOverview ctl={ctl} />

      <DocumentsListSection ctl={ctl} />

      <DocumentsActivityCards ctl={ctl} />

      <SelectedDocumentPanel ctl={ctl} />

      <DocumentsUploadModal
        isOpen={isUploadModalOpen}
        canUpload={capabilities.canUpload}
        isUploading={isUploading}
        acceptedTypesLabel={ACCEPTED_UPLOAD_TYPES_LABEL}
        collections={uploadCollections.items}
        collectionSearch={uploadCollections}
        onRequestClose={handleUploadModalClose}
        onCancelAll={cancelAllUploads}
        onCancelItem={cancelUploadAtIndex}
        onRetryItem={handleRetryItem}
        onFilesSelected={handleFileUpload}
        feedback={uploadFeedback}
        progress={uploadProgress}
        uploadHistory={uploadHistory}
      />

      {assignDocumentId ? (
        <AssignCollectionsDialog
          documentName={assignDocumentName}
          collectionList={assignCollections.items}
          collectionSearch={assignCollections}
          loadingCollections={
            assignCollections.query.isLoading || docCollectionsQuery.isLoading
          }
          currentCollectionIds={(docCollectionsQuery.data?.items ?? []).map(
            (c) => c.collection_id,
          )}
          saving={assignCollectionsMutation.isPending}
          saveError={assignSaveError}
          onSave={(collectionIds) =>
            assignCollectionsMutation.mutate(collectionIds)
          }
          onClose={() => {
            setAssignDocumentId(null);
            setAssignDocumentName("");
            setAssignSaveError(null);
          }}
        />
      ) : null}

      <DeleteConfirmModal
        open={deleteModalState.open}
        filenames={deleteModalState.filenames}
        onCancel={() =>
          setDeleteModalState({ open: false, documentId: null, filenames: [] })
        }
        onConfirm={() => {
          if (deleteModalState.documentId) {
            deleteMutation.mutate(deleteModalState.documentId);
          } else {
            bulkDeleteMutation.mutate(Array.from(selectedIds));
          }
          setDeleteModalState({ open: false, documentId: null, filenames: [] });
        }}
      />
    </section>
  );
}
