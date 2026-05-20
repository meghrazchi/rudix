import type { ReactNode } from "react";

type EmptyStateProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
};

export function EmptyState({
  title = "No data available",
  description,
  action,
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <section
      aria-label="Empty state"
      className={
        className ??
        `rounded-lg border border-[#e4e1f2] bg-[#faf9ff] ${
          compact ? "px-3 py-2" : "px-4 py-6 text-center"
        }`
      }
    >
      <p
        className={`${compact ? "text-sm" : "text-base"} font-semibold text-[#2a2640]`}
      >
        {title}
      </p>
      {description ? (
        <p
          className={`${compact ? "mt-1 text-xs" : "mt-1 text-sm"} text-[#68647b]`}
        >
          {description}
        </p>
      ) : null}
      {action ? (
        <div className={compact ? "mt-2" : "mt-4"}>{action}</div>
      ) : null}
    </section>
  );
}
