/** Compact label/value metric card used on the document detail page. */
export function MetricCard({
  label,
  value,
  valueClass,
  plain = true,
  mono = false,
  wrap = false,
}: {
  label: string;
  value: string | number;
  valueClass?: string;
  plain?: boolean;
  mono?: boolean;
  wrap?: boolean;
}) {
  if (!plain && valueClass) {
    return (
      <div className="flex h-[92px] flex-col rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
        <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {label}
        </p>
        <span className={valueClass}>{value}</span>
      </div>
    );
  }

  return (
    <div className="flex h-[92px] flex-col rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p
        className={`text-sm font-semibold text-[#2a2640] ${wrap ? "leading-relaxed break-all" : ""}`}
        title={typeof value === "string" ? value : undefined}
        style={
          mono
            ? {
                fontFamily:
                  "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace",
              }
            : undefined
        }
      >
        {value}
      </p>
    </div>
  );
}
