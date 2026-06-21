"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getDocumentVersions,
  type DocumentVersionResponse,
} from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";

type DocumentVersionHistoryPanelProps = {
  documentId: string;
};

const CHANGE_REASON_LABELS: Record<string, string> = {
  initial_upload: "Initial upload",
  content_update: "Content update",
  metadata_update: "Metadata update",
  connector_sync: "Connector sync",
  reindex: "Re-indexed",
  tombstone: "Tombstoned",
};

function changeReasonLabel(reason: string): string {
  return CHANGE_REASON_LABELS[reason] ?? reason.replace(/_/g, " ");
}

function changeReasonIcon(reason: string): string {
  if (reason === "initial_upload") return "upload_file";
  if (reason === "content_update") return "edit_document";
  if (reason === "connector_sync") return "sync";
  if (reason === "reindex") return "refresh";
  if (reason === "tombstone") return "delete";
  return "history";
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function shortHash(hash: string | null | undefined): string | null {
  if (!hash) return null;
  return hash.slice(0, 12);
}

function VersionBadge({ isCurrent }: { isCurrent: boolean }) {
  if (!isCurrent) return null;
  return (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold tracking-wide text-emerald-800 uppercase">
      active
    </span>
  );
}

function VersionStatusChip({ status }: { status: string }) {
  const color =
    status === "indexed"
      ? "bg-emerald-100 text-emerald-800"
      : status === "processing"
        ? "bg-blue-100 text-blue-800"
        : status === "failed"
          ? "bg-rose-100 text-rose-800"
          : "bg-slate-100 text-slate-600";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${color}`}
    >
      {status}
    </span>
  );
}

function VersionCard({ version }: { version: DocumentVersionResponse }) {
  const hash = shortHash(version.content_hash);

  return (
    <article
      aria-label={`Version ${version.version_number}`}
      className={`rounded-lg border p-4 ${
        version.is_current
          ? "border-[#3525cd]/30 bg-[#f8f7ff]"
          : "border-[#e4e1f2] bg-white"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-[18px] text-[#5d58a8]"
          >
            {changeReasonIcon(version.change_reason)}
          </span>
          <span className="text-sm font-bold text-[#2a2640]">
            v{version.version_number}
          </span>
          <VersionBadge isCurrent={version.is_current} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <VersionStatusChip status={version.status} />
          <span className="rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-semibold text-[#3525cd]">
            {changeReasonLabel(version.change_reason)}
          </span>
        </div>
      </div>

      <dl className="mt-3 grid gap-y-1.5 text-xs">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-[#69637f]">Created</dt>
          <dd className="font-semibold text-[#2a2640]">
            {formatDateTime(version.created_at)}
          </dd>
        </div>

        {version.indexed_at ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Indexed at</dt>
            <dd className="font-semibold text-[#2a2640]">
              {formatDateTime(version.indexed_at)}
            </dd>
          </div>
        ) : null}

        {version.filename ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Filename</dt>
            <dd className="truncate font-semibold text-[#2a2640]">
              {version.filename}
            </dd>
          </div>
        ) : null}

        {version.page_count != null ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Pages</dt>
            <dd className="font-semibold text-[#2a2640]">
              {version.page_count}
            </dd>
          </div>
        ) : null}

        {version.chunk_count != null ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Chunks</dt>
            <dd className="font-semibold text-[#2a2640]">
              {version.chunk_count}
            </dd>
          </div>
        ) : null}

        {hash ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Content hash</dt>
            <dd
              className="font-mono text-[10px] text-[#5c5874]"
              title={version.content_hash ?? undefined}
            >
              {hash}&hellip;
            </dd>
          </div>
        ) : null}

        {version.embedding_model ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Embedding model</dt>
            <dd className="font-semibold text-[#2a2640]">
              {version.embedding_model}
            </dd>
          </div>
        ) : null}

        {version.index_version ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Index version</dt>
            <dd className="font-semibold text-[#2a2640]">
              {version.index_version}
            </dd>
          </div>
        ) : null}

        {version.chunking_profile_snapshot?.strategy ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Chunking strategy</dt>
            <dd className="font-semibold text-[#2a2640]">
              {String(version.chunking_profile_snapshot.strategy)}
            </dd>
          </div>
        ) : null}

        {version.source_updated_at ? (
          <div className="flex items-center justify-between gap-3">
            <dt className="text-[#69637f]">Source updated</dt>
            <dd className="font-semibold text-[#2a2640]">
              {formatDateTime(version.source_updated_at)}
            </dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

export function DocumentVersionHistoryPanel({
  documentId,
}: DocumentVersionHistoryPanelProps) {
  const versionsQuery = useQuery({
    queryKey: queryKeys.documents.versions(documentId),
    queryFn: () => getDocumentVersions(documentId),
  });

  if (versionsQuery.isLoading) {
    return (
      <LoadingState
        className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]"
        title="Loading version history…"
      />
    );
  }

  if (versionsQuery.isError) {
    return (
      <ErrorState
        error={versionsQuery.error}
        description={getApiErrorMessage(versionsQuery.error)}
        onRetry={() => void versionsQuery.refetch()}
      />
    );
  }

  const versions = versionsQuery.data?.items ?? [];

  if (versions.length === 0) {
    return (
      <div className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-6 text-center">
        <span
          aria-hidden="true"
          className="material-symbols-outlined text-[32px] text-[#b0aac8]"
        >
          history
        </span>
        <p className="mt-2 text-sm text-[#69637f]">No version history yet.</p>
        <p className="text-xs text-[#8e89a4]">
          Versions are recorded on upload and each re-index.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[#69637f]">
          {versions.length} version{versions.length !== 1 ? "s" : ""} recorded
        </p>
      </div>
      <ol aria-label="Version history" className="space-y-3">
        {versions.map((v) => (
          <li key={v.version_id}>
            <VersionCard version={v} />
          </li>
        ))}
      </ol>
    </div>
  );
}
