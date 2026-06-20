type SkeletonBlockProps = {
  rows?: number;
  compact?: boolean;
  className?: string;
};

type SkeletonRowProps = {
  widthClass?: string;
  compact?: boolean;
};

function SkeletonRow({
  widthClass = "w-full",
  compact = false,
}: SkeletonRowProps) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-full bg-[#e8e5f5] ${compact ? "h-2" : "h-2.5"} ${widthClass}`}
    />
  );
}

const ROW_WIDTHS = ["w-full", "w-4/5", "w-3/5", "w-2/3", "w-1/2"];

export function SkeletonBlock({
  rows = 3,
  compact = false,
  className,
}: SkeletonBlockProps) {
  return (
    <div
      role="status"
      aria-label="Loading content"
      aria-live="polite"
      className={
        className ??
        `rounded-lg border border-[#e4e1f2] bg-[#faf9ff] ${compact ? "px-3 py-2" : "px-4 py-4"}`
      }
    >
      <div className={`space-y-${compact ? "2" : "3"}`}>
        {Array.from({ length: rows }, (_, index) => (
          <SkeletonRow
            key={index}
            widthClass={ROW_WIDTHS[index % ROW_WIDTHS.length]}
            compact={compact}
          />
        ))}
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  );
}
