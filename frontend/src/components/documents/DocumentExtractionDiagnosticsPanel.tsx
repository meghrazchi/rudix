"use client";

import type { DocumentProfile, ExtractionSnapshot } from "@/lib/api/documents";

type DocumentExtractionDiagnosticsPanelProps = {
  snapshot: ExtractionSnapshot;
};

const PROFILE_LABELS: Record<DocumentProfile, string> = {
  text_based: "Text-based",
  scanned: "Scanned",
  mixed: "Mixed (text + scanned)",
  table_heavy: "Table-heavy",
  figure_heavy: "Figure-heavy",
  form_like: "Form-like",
  encrypted: "Encrypted",
  corrupted: "Corrupted",
  unsupported: "Unsupported",
};

const PROFILE_BADGE_CLASSES: Record<DocumentProfile, string> = {
  text_based: "bg-green-100 text-green-800",
  scanned: "bg-yellow-100 text-yellow-800",
  mixed: "bg-blue-100 text-blue-800",
  table_heavy: "bg-purple-100 text-purple-800",
  figure_heavy: "bg-indigo-100 text-indigo-800",
  form_like: "bg-orange-100 text-orange-800",
  encrypted: "bg-red-100 text-red-800",
  corrupted: "bg-red-100 text-red-800",
  unsupported: "bg-gray-100 text-gray-600",
};

function MetricRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-gray-100 py-1.5 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-medium text-gray-800">{value}</span>
    </div>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80 ? "bg-green-500" : pct >= 50 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-sm font-medium text-gray-800">{pct}%</span>
    </div>
  );
}

export function DocumentExtractionDiagnosticsPanel({
  snapshot,
}: DocumentExtractionDiagnosticsPanelProps) {
  const profile = snapshot.document_profile;
  const profileLabel = PROFILE_LABELS[profile] ?? profile;
  const profileBadgeClass =
    PROFILE_BADGE_CLASSES[profile] ?? "bg-gray-100 text-gray-600";

  const pagesWithOcr = snapshot.pages.filter((p) => p.requires_ocr).length;
  const pagesWithTables = snapshot.pages.filter(
    (p) => p.table_block_count > 0,
  ).length;
  const pagesWithImages = snapshot.pages.filter(
    (p) => p.image_block_count > 0,
  ).length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${profileBadgeClass}`}
        >
          {profileLabel}
        </span>
        {snapshot.is_encrypted && (
          <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
            Encrypted
          </span>
        )}
      </div>

      <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
        <div className="px-4 py-3">
          <MetricRow label="Pages" value={snapshot.page_count} />
          <MetricRow label="Text blocks" value={snapshot.total_text_blocks} />
          <MetricRow label="Tables found" value={snapshot.total_table_blocks} />
          <MetricRow
            label="Images / figures"
            value={snapshot.total_image_blocks}
          />
          <MetricRow
            label="Pages requiring OCR"
            value={pagesWithOcr > 0 ? pagesWithOcr : "None"}
          />
          <MetricRow
            label="Pages with tables"
            value={pagesWithTables > 0 ? pagesWithTables : "None"}
          />
          <MetricRow
            label="Pages with images"
            value={pagesWithImages > 0 ? pagesWithImages : "None"}
          />
          <MetricRow
            label="Extraction engine"
            value={snapshot.extraction_engine}
          />
          <MetricRow
            label="Extraction confidence"
            value={<ConfidenceBar value={snapshot.extraction_confidence} />}
          />
          <MetricRow label="Duration" value={`${snapshot.duration_ms} ms`} />
        </div>
      </div>

      {snapshot.warnings.length > 0 && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3">
          <p className="mb-1 text-xs font-semibold text-yellow-800">
            Extraction warnings ({snapshot.warnings.length})
          </p>
          <ul className="space-y-1">
            {snapshot.warnings.slice(0, 5).map((w, i) => (
              <li key={i} className="text-xs leading-snug text-yellow-700">
                {w}
              </li>
            ))}
            {snapshot.warnings.length > 5 && (
              <li className="text-xs text-yellow-600 italic">
                +{snapshot.warnings.length - 5} more warnings
              </li>
            )}
          </ul>
        </div>
      )}

      {snapshot.pages.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold tracking-wide text-gray-500 uppercase">
            Page breakdown
          </p>
          <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
            {snapshot.pages.map((page) => (
              <div
                key={page.page_number}
                className="flex items-center gap-2 rounded bg-gray-50 px-2 py-1 text-xs text-gray-600"
              >
                <span className="w-14 shrink-0 font-medium">
                  Page {page.page_number}
                </span>
                <span className="w-20 text-gray-500">
                  {page.char_count.toLocaleString()} chars
                </span>
                {page.table_block_count > 0 && (
                  <span className="text-purple-600">
                    {page.table_block_count}T
                  </span>
                )}
                {page.image_block_count > 0 && (
                  <span className="text-indigo-600">
                    {page.image_block_count}I
                  </span>
                )}
                {page.requires_ocr && (
                  <span className="font-medium text-yellow-700">OCR</span>
                )}
                {page.warnings.length > 0 && (
                  <span className="text-red-500" title={page.warnings[0]}>
                    ⚠
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
