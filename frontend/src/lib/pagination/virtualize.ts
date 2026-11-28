const DEFAULT_TABLE_VIRTUALIZE_MIN_ROWS = 200;

/** Parses a positive row threshold; anything else falls back to the default. */
export function parseVirtualizeMinRows(value: string | undefined): number {
  if (!value) {
    return DEFAULT_TABLE_VIRTUALIZE_MIN_ROWS;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return DEFAULT_TABLE_VIRTUALIZE_MIN_ROWS;
  }
  return parsed;
}

/**
 * Tables render every row up to this count and virtualise above it
 * (`NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS`, default 200).
 */
export function tableVirtualizeMinRows(): number {
  return parseVirtualizeMinRows(
    process.env.NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS,
  );
}
