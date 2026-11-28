/** Label/value metric card of the inline document detail panel. */
export function ListMetricCard({
  label,
  value,
  valueClass,
  plain = true,
  mono = false,
}: {
  label: string;
  value: string | number;
  valueClass?: string;
  plain?: boolean;
  mono?: boolean;
}) {
  if (!plain && valueClass) {
    return (
      <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
        <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {label}
        </p>
        <span className={valueClass}>{value}</span>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p
        className="text-sm font-semibold text-[#2a2640]"
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
