"use client";

// ---------------------------------------------------------------------------
// ConnectorIngestionStatusBadge
//
// Renders a styled pill badge for a connector-ingested document's lifecycle
// status.  Covers all statuses introduced in F245 plus the shared document
// statuses that connector files can reach (indexed, processing, failed, etc.).
// ---------------------------------------------------------------------------

type StatusMeta = {
  label: string;
  description: string;
  colorClass: string;
};

export type ConnectorFileStatus =
  // Connector-specific lifecycle statuses (F245)
  | "pending_scan"
  | "infected"
  | "extraction_failed"
  | "ocr_applied"
  | "skipped"
  | "unsupported"
  // Shared document pipeline statuses
  | "uploaded"
  | "processing"
  | "indexed"
  | "failed"
  | "quarantined"
  | "blocked"
  | "delete_requested"
  | "deleting"
  | "deleted"
  | "retained_by_policy";

const STATUS_META: Record<ConnectorFileStatus, StatusMeta> = {
  // --- F245 connector statuses ---
  pending_scan: {
    label: "Pending scan",
    description:
      "File has been received and is waiting for the security scan to run.",
    colorClass: "bg-yellow-100 text-yellow-800",
  },
  infected: {
    label: "Infected",
    description:
      "ClamAV detected malware in this file. It will not be indexed.",
    colorClass: "bg-red-100 text-red-800",
  },
  extraction_failed: {
    label: "Extraction failed",
    description:
      "Text could not be extracted from this file. Check the document detail for diagnostics.",
    colorClass: "bg-red-100 text-red-700",
  },
  ocr_applied: {
    label: "OCR applied",
    description:
      "The file was processed with OCR because it contained scanned pages.",
    colorClass: "bg-teal-100 text-teal-800",
  },
  skipped: {
    label: "Skipped",
    description:
      "This file was not re-indexed because an identical copy already exists in the workspace.",
    colorClass: "bg-gray-100 text-gray-600",
  },
  unsupported: {
    label: "Unsupported",
    description:
      "This file format is not supported for indexing and was not ingested.",
    colorClass: "bg-gray-100 text-gray-500",
  },
  // --- Shared pipeline statuses ---
  uploaded: {
    label: "Uploaded",
    description:
      "File has been uploaded and is waiting for the processing pipeline.",
    colorClass: "bg-blue-100 text-blue-700",
  },
  processing: {
    label: "Processing",
    description: "Text extraction, chunking, and embedding are in progress.",
    colorClass: "bg-blue-100 text-blue-800",
  },
  indexed: {
    label: "Indexed",
    description:
      "File has been fully indexed and is available for search and citations.",
    colorClass: "bg-green-100 text-green-800",
  },
  failed: {
    label: "Failed",
    description:
      "An error occurred during processing. The document may be retried.",
    colorClass: "bg-red-100 text-red-800",
  },
  quarantined: {
    label: "Quarantined",
    description: "File has been quarantined pending administrator review.",
    colorClass: "bg-orange-100 text-orange-800",
  },
  blocked: {
    label: "Blocked",
    description: "File was blocked by a data loss prevention (DLP) policy.",
    colorClass: "bg-orange-100 text-orange-700",
  },
  delete_requested: {
    label: "Delete requested",
    description: "Deletion has been requested and is pending confirmation.",
    colorClass: "bg-gray-100 text-gray-600",
  },
  deleting: {
    label: "Deleting",
    description: "File is being permanently deleted from the workspace.",
    colorClass: "bg-gray-100 text-gray-500",
  },
  deleted: {
    label: "Deleted",
    description: "File has been permanently deleted.",
    colorClass: "bg-gray-100 text-gray-400",
  },
  retained_by_policy: {
    label: "Retained",
    description: "File is under a retention policy and cannot be deleted yet.",
    colorClass: "bg-indigo-100 text-indigo-700",
  },
};

const FALLBACK_META: StatusMeta = {
  label: "Unknown",
  description: "Status is not recognised.",
  colorClass: "bg-gray-100 text-gray-500",
};

// ---------------------------------------------------------------------------
// ConnectorIngestionStatusBadge component
// ---------------------------------------------------------------------------

type ConnectorIngestionStatusBadgeProps = {
  status: string;
  showTooltip?: boolean;
  className?: string;
};

export function ConnectorIngestionStatusBadge({
  status,
  showTooltip = true,
  className = "",
}: ConnectorIngestionStatusBadgeProps) {
  const meta = STATUS_META[status as ConnectorFileStatus] ?? FALLBACK_META;

  return (
    <span
      title={showTooltip ? meta.description : undefined}
      className={`inline-flex cursor-default items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.colorClass} ${className}`}
    >
      {meta.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ConnectorIngestionStatusRow — for use inside detail panels and tables
// ---------------------------------------------------------------------------

type ConnectorIngestionStatusRowProps = {
  status: string;
  errorMessage?: string | null;
  className?: string;
};

export function ConnectorIngestionStatusRow({
  status,
  errorMessage,
  className = "",
}: ConnectorIngestionStatusRowProps) {
  const isTerminalError = [
    "infected",
    "extraction_failed",
    "failed",
    "blocked",
  ].includes(status);

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="flex items-center gap-2">
        <span className="w-20 shrink-0 text-xs font-medium text-gray-500">
          Status
        </span>
        <ConnectorIngestionStatusBadge status={status} />
      </div>
      {isTerminalError && errorMessage && (
        <div className="flex items-start gap-2">
          <span className="w-20 shrink-0 text-xs font-medium text-gray-500">
            Error
          </span>
          <p className="text-xs break-words text-red-600">{errorMessage}</p>
        </div>
      )}
    </div>
  );
}
