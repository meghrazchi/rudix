import type { EvaluationRunHistoryRecord } from "@/components/evaluations/evaluation-view-model";

const HISTORY_STORAGE_KEY = "rudix.evaluations.run-history.v1";
const HISTORY_MAX_ITEMS = 30;

function canUseStorage(): boolean {
  return typeof window !== "undefined" && Boolean(window.localStorage);
}

function isValidRecord(value: unknown): value is EvaluationRunHistoryRecord {
  if (typeof value !== "object" || value == null || Array.isArray(value)) {
    return false;
  }

  const row = value as Record<string, unknown>;
  return typeof row.runId === "string" && typeof row.datasetId === "string";
}

export function readEvaluationRunHistory(): EvaluationRunHistoryRecord[] {
  if (!canUseStorage()) {
    return [];
  }

  const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.filter(isValidRecord).slice(0, HISTORY_MAX_ITEMS);
  } catch {
    return [];
  }
}

export function writeEvaluationRunHistory(
  records: EvaluationRunHistoryRecord[],
): void {
  if (!canUseStorage()) {
    return;
  }

  const deduplicated = new Map<string, EvaluationRunHistoryRecord>();
  for (const record of records) {
    deduplicated.set(record.runId, record);
  }

  const sorted = [...deduplicated.values()]
    .sort((left, right) => {
      const leftTs = Date.parse(left.updatedAt);
      const rightTs = Date.parse(right.updatedAt);
      const safeLeft = Number.isFinite(leftTs) ? leftTs : 0;
      const safeRight = Number.isFinite(rightTs) ? rightTs : 0;
      return safeRight - safeLeft;
    })
    .slice(0, HISTORY_MAX_ITEMS);

  window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(sorted));
}

export function upsertEvaluationRunHistory(
  nextRecord: EvaluationRunHistoryRecord,
): EvaluationRunHistoryRecord[] {
  const current = readEvaluationRunHistory();
  const merged = [
    nextRecord,
    ...current.filter((row) => row.runId !== nextRecord.runId),
  ];
  writeEvaluationRunHistory(merged);
  return readEvaluationRunHistory();
}
