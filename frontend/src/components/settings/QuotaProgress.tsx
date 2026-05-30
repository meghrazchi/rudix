"use client";

type QuotaProgressProps = {
  label: string;
  description?: string;
  used: number;
  total: number | null;
  unit?: string;
  warnAt?: number;
  criticalAt?: number;
};

function formatValue(value: number, unit: string): string {
  if (unit === "GB" || unit === "TB") {
    if (value >= 1000) return `${(value / 1000).toFixed(1)} T`;
    return `${value.toFixed(1)} ${unit}`;
  }
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(Math.round(value));
}

function formatTotal(total: number | null, unit: string): string {
  if (total === null) return "Unlimited";
  return formatValue(total, unit);
}

export function QuotaProgress({
  label,
  description,
  used,
  total,
  unit = "",
  warnAt = 80,
  criticalAt = 90,
}: QuotaProgressProps) {
  const pct = total !== null && total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const isUnlimited = total === null;

  const barColor =
    pct >= 100
      ? "bg-rose-500"
      : pct >= criticalAt
        ? "bg-orange-500"
        : pct >= warnAt
          ? "bg-amber-400"
          : "bg-[#3525cd]";

  const pctLabel =
    pct >= 100
      ? "Quota reached"
      : pct >= criticalAt
        ? `${Math.round(pct)}% — critical`
        : pct >= warnAt
          ? `${Math.round(pct)}% — warning`
          : `${Math.round(pct)}%`;

  return (
    <div>
      <div className="flex items-end justify-between mb-1.5">
        <div>
          <p className="text-sm font-semibold text-[#1b1b24]">{label}</p>
          {description && (
            <p className="text-xs text-[#464555]">{description}</p>
          )}
        </div>
        <p className="shrink-0 font-mono text-xs text-[#464555] ml-4">
          {isUnlimited ? (
            <span>
              {formatValue(used, unit)}
              {unit ? ` ${unit}` : ""} / Unlimited
            </span>
          ) : (
            <span>
              {formatValue(used, unit)} / {formatTotal(total, unit)}
              {unit ? ` ${unit}` : ""}
            </span>
          )}
        </p>
      </div>
      <div
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${pctLabel}`}
        className="h-2 w-full rounded-full bg-[#e4e1ee] overflow-hidden"
      >
        {!isUnlimited && (
          <div
            className={`h-full rounded-full transition-all duration-700 ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {!isUnlimited && pct >= warnAt && (
        <p
          className={[
            "mt-1 text-xs font-semibold",
            pct >= 100
              ? "text-rose-600"
              : pct >= criticalAt
                ? "text-orange-600"
                : "text-amber-600",
          ].join(" ")}
          role="alert"
        >
          {pct >= 100
            ? "Quota reached — upgrade or reduce usage."
            : pct >= criticalAt
              ? `${Math.round(pct)}% used — quota almost exhausted.`
              : `${Math.round(pct)}% used — approaching limit.`}
        </p>
      )}
    </div>
  );
}
