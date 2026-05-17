type LoadingStateProps = {
  title?: string;
  description?: string;
  compact?: boolean;
  className?: string;
};

export function LoadingState({
  title = "Loading...",
  description,
  compact = false,
  className,
}: LoadingStateProps) {
  return (
    <section
      role="status"
      aria-live="polite"
      aria-label="Loading state"
      className={
        className ??
        `rounded-lg border border-[#e4e1f2] bg-[#faf9ff] ${
          compact ? "px-3 py-2" : "px-4 py-4"
        } text-sm text-[#5f5b72]`
      }
    >
      <p className={compact ? "font-medium" : "font-semibold"}>{title}</p>
      {description ? <p className="mt-1">{description}</p> : null}
    </section>
  );
}
