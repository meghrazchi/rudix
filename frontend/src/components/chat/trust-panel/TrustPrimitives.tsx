import type { ReactNode } from "react";

export function SectionHeader({
  icon,
  label,
}: {
  icon: string;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-[#f0ecf9] text-[#3525cd]">
        <span
          className="material-symbols-outlined text-[14px]"
          aria-hidden="true"
        >
          {icon}
        </span>
      </span>
      <span className="text-[10px] font-bold tracking-[0.18em] text-[#3525cd] uppercase">
        {label}
      </span>
    </div>
  );
}

export function StatRow({
  label,
  value,
  subtle,
}: {
  label: string;
  value: ReactNode;
  subtle?: boolean;
}) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-center justify-between gap-2 py-0.5">
      <span
        className={`text-[11px] ${subtle ? "text-[#9d98b5]" : "text-[#6a6780]"}`}
      >
        {label}
      </span>
      <span className="text-[11px] font-medium text-[#2f2a46]">{value}</span>
    </div>
  );
}

export function WarningBanner({
  children,
  tone = "warning",
}: {
  children: ReactNode;
  tone?: "warning" | "neutral";
}) {
  const isNeutral = tone === "neutral";
  return (
    <div
      className={`flex items-start gap-1.5 rounded-lg border px-3 py-2 text-[11px] ${
        isNeutral
          ? "border-[#d7d4e8] bg-[#f5f2ff] text-[#4f4b63]"
          : "border-amber-200 bg-amber-50 text-amber-900"
      }`}
    >
      <span
        className={`material-symbols-outlined shrink-0 text-[14px] ${
          isNeutral ? "text-[#9d98b5]" : "text-amber-700"
        }`}
        aria-hidden="true"
      >
        {isNeutral ? "info" : "warning"}
      </span>
      <span>{children}</span>
    </div>
  );
}
