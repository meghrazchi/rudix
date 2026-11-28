"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { OnboardingCtaBanner } from "@/components/onboarding/OnboardingCtaBanner";
import { ACCEPTED_UPLOAD_TYPES_LABEL } from "@/components/documents/upload-validation";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError } from "@/lib/forbidden";

import { DocumentsFilterBar } from "@/components/documents/list/DocumentsFilterBar";
import { DocumentsTable } from "@/components/documents/list/DocumentsTable";
import { DocumentsTableFooter } from "@/components/documents/list/DocumentsTableFooter";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Filter bar, list states, documents table, bulk bar, and pagination. */
export function DocumentsListSection({
  ctl,
}: {
  ctl: DocumentsPageController;
}) {
  const {
    setIsUploadModalOpen,
    tp,
    capabilities,
    actionFeedback,
    actionRequestId,
    setFilenameSearch,
    debouncedFilenameSearch,
    documentsQuery,
    documents,
    listForbidden,
  } = ctl;
  return (
    <section className="space-y-4 rounded-xl border border-[#e5e3f1] bg-white p-4 shadow-sm">
      <DocumentsFilterBar ctl={ctl} />

      {actionFeedback ? (
        <p
          role="status"
          className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
        >
          {actionFeedback}
          {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
        </p>
      ) : null}

      {documentsQuery.isLoading ? <LoadingState title={tp("loading")} /> : null}

      {documentsQuery.isError && listForbidden ? (
        <ForbiddenState
          compact
          title={tp("accessDenied")}
          description={tp("accessDeniedDesc")}
          requestId={extractRequestIdFromError(documentsQuery.error)}
        />
      ) : null}

      {documentsQuery.isError && !listForbidden ? (
        <ErrorState
          error={documentsQuery.error}
          description={getApiErrorMessage(documentsQuery.error)}
          onRetry={() => {
            void documentsQuery.refetch();
          }}
        />
      ) : null}

      {!documentsQuery.isLoading &&
      !documentsQuery.isError &&
      documents.length === 0 ? (
        <EmptyState
          title={tp("noDocumentsFound")}
          description={
            debouncedFilenameSearch
              ? tp("noDocumentsMatch", { query: debouncedFilenameSearch })
              : tp("uploadFirst", { types: ACCEPTED_UPLOAD_TYPES_LABEL })
          }
          action={
            debouncedFilenameSearch ? (
              <button
                type="button"
                onClick={() => setFilenameSearch("")}
                className="rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
              >
                {tp("clearSearch")}
              </button>
            ) : capabilities.canUpload ? (
              <button
                type="button"
                onClick={() => setIsUploadModalOpen(true)}
                className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
              >
                {tp("uploadDocument")}
              </button>
            ) : (
              <p className="text-xs text-[#6a6780]">{tp("roleCannotUpload")}</p>
            )
          }
        />
      ) : null}

      {!documentsQuery.isLoading &&
      !documentsQuery.isError &&
      documents.length === 0 &&
      !debouncedFilenameSearch ? (
        <div className="mt-4">
          <OnboardingCtaBanner
            title={tp("onboardingTitle")}
            description={tp("onboardingDescription")}
            actionLabel={tp("onboardingAction")}
            actionHref="/chat"
            secondaryLabel={tp("goToChat")}
            secondaryHref="/chat"
          />
        </div>
      ) : null}

      {!documentsQuery.isLoading &&
      !documentsQuery.isError &&
      documents.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-[#e5e3f1]">
          <DocumentsTable ctl={ctl} />
          <DocumentsTableFooter ctl={ctl} />
        </div>
      ) : null}
    </section>
  );
}
