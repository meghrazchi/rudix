"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { CitationPreviewDrawer } from "@/components/chat/DocumentPreviewModal";
import { CitationEvidenceCallout } from "@/components/documents/detail/CitationEvidenceCallout";
import { DocumentDetailTabs } from "@/components/documents/detail/DocumentDetailTabs";
import { DocumentHeaderCard } from "@/components/documents/detail/DocumentHeaderCard";
import { DocumentLifecycleTimeline } from "@/components/documents/detail/DocumentLifecycleTimeline";
import { OriginalPreviewCard } from "@/components/documents/detail/OriginalPreviewCard";
import { QualityWorkflowCard } from "@/components/documents/detail/QualityWorkflowCard";
import { useDocumentDetail } from "@/components/documents/detail/useDocumentDetail";
import { getApiErrorMessage } from "@/lib/api/errors";

type DocumentDetailPageProps = {
  documentId: string;
};

export function DocumentDetailPage({ documentId }: DocumentDetailPageProps) {
  const ctl = useDocumentDetail(documentId);
  const {
    td,
    detailQuery,
    statusQuery,
    notFoundOrInaccessible,
    actionFeedback,
    actionRequestId,
    detail,
    currentStatus,
    lifecycle,
    previewCitationSet,
    setPreviewCitationSet,
  } = ctl;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {td("eyebrow")}
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {td("title")}
        </h1>
        <p className="text-sm text-[#68647b]">{td("description")}</p>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        {detailQuery.isLoading ? (
          <LoadingState
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]"
            title={td("loading")}
          />
        ) : null}

        {notFoundOrInaccessible ? (
          <EmptyState
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-6 text-center"
            title={td("notFoundTitle")}
            description={td("notFoundDesc")}
          />
        ) : null}

        {!detailQuery.isLoading &&
        detailQuery.isError &&
        !notFoundOrInaccessible ? (
          <ErrorState
            error={detailQuery.error}
            description={getApiErrorMessage(detailQuery.error)}
            onRetry={() => {
              void detailQuery.refetch();
              void statusQuery.refetch();
            }}
          />
        ) : null}

        {detail && currentStatus && !notFoundOrInaccessible ? (
          <div className="space-y-5">
            {actionFeedback ? (
              <p
                role="status"
                className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
              >
                {actionFeedback}
                {actionRequestId
                  ? ` (${td("traceId")}: ${actionRequestId})`
                  : ""}
              </p>
            ) : null}

            <DocumentHeaderCard
              ctl={ctl}
              detail={detail}
              currentStatus={currentStatus}
            />

            <CitationEvidenceCallout ctl={ctl} detail={detail} />

            <div className="grid items-start gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-8">
                <QualityWorkflowCard ctl={ctl} detail={detail} />
                <DocumentDetailTabs
                  ctl={ctl}
                  detail={detail}
                  currentStatus={currentStatus}
                />
              </div>
              <DocumentLifecycleTimeline td={td} lifecycle={lifecycle} />
            </div>

            <OriginalPreviewCard ctl={ctl} detail={detail} />
          </div>
        ) : null}
        {previewCitationSet ? (
          <CitationPreviewDrawer
            citations={previewCitationSet.citations}
            initialIndex={previewCitationSet.initialIndex}
            onClose={() => setPreviewCitationSet(null)}
          />
        ) : null}
      </section>
    </section>
  );
}
