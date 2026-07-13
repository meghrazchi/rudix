import type { ReactNode } from "react";
import { AlertTriangle, ArrowRight, X } from "lucide-react";

export function ReportHeader({
  title,
  description,
  eyebrow = "Reports",
  actions,
}: {
  title: string;
  description: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <p className="text-xs font-bold tracking-[0.16em] text-[#5d58a8] uppercase">
          {eyebrow}
        </p>
        <h1 className="mt-1 text-2xl font-extrabold text-[#2a2640] sm:text-3xl">
          {title}
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-[#68647b]">{description}</p>
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </header>
  );
}

export function KpiCard({
  label,
  value,
  change,
  description,
}: {
  label: string;
  value: string;
  change?: string;
  description?: string;
}) {
  return (
    <article className="rounded-xl border border-[#dfdced] bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold text-[#68647b]">{label}</p>
      <div className="mt-2 flex items-end justify-between gap-3">
        <p className="text-2xl font-extrabold text-[#2a2640]">{value}</p>
        {change ? (
          <p className="text-xs font-bold text-emerald-700">{change}</p>
        ) : null}
      </div>
      {description ? (
        <p className="mt-2 text-xs text-[#777287]">{description}</p>
      ) : null}
    </article>
  );
}

export function ChartCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[#dfdced] bg-white p-4 shadow-sm">
      <h2 className="font-bold text-[#2a2640]">{title}</h2>
      {description ? (
        <p className="mt-1 text-xs text-[#68647b]">{description}</p>
      ) : null}
      <div className="mt-4 min-h-44">{children}</div>
    </section>
  );
}

export function ReportDataTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: string[];
  rows: ReactNode[][];
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-[#dfdced] bg-white shadow-sm">
      <table className="w-full min-w-[560px] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[#f7f5ff] text-xs text-[#5f5b72] uppercase">
          <tr>
            {columns.map((column) => (
              <th className="px-4 py-3 font-bold" key={column}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#ebe8f4]">
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td className="px-4 py-3 text-[#403c52]" key={cellIndex}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STATUS_CLASSES = {
  healthy: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-900",
  critical: "bg-rose-100 text-rose-800",
  neutral: "bg-slate-100 text-slate-700",
};

export function StatusBadge({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: keyof typeof STATUS_CLASSES;
}) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-1 text-xs font-bold ${STATUS_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}

export function RecommendedActionCard({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <aside className="rounded-xl border border-[#cfc9ff] bg-[#f2efff] p-4">
      <div className="flex gap-3">
        <ArrowRight
          className="mt-0.5 h-4 w-4 shrink-0 text-[#3525cd]"
          aria-hidden
        />
        <div>
          <h2 className="font-bold text-[#2a2640]">{title}</h2>
          <p className="mt-1 text-sm text-[#5f5b72]">{description}</p>
          {action ? <div className="mt-3">{action}</div> : null}
        </div>
      </div>
    </aside>
  );
}

export function PartialDataState({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
    >
      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
      <p>
        <strong>Partial data.</strong> {message}
      </p>
    </div>
  );
}

export function DetailDrawer({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-950/30"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
          <button
            type="button"
            aria-label="Close details"
            onClick={onClose}
            className="rounded-lg p-2 hover:bg-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-5">{children}</div>
      </aside>
    </div>
  );
}
