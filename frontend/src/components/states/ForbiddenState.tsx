import Link from "next/link";

import { getSupportAction, sanitizeRequestId } from "@/lib/forbidden";

type ForbiddenStateProps = {
  title?: string;
  description?: string;
  requestId?: string | null;
  backHref?: string;
  backLabel?: string;
  compact?: boolean;
};

export function ForbiddenState({
  title = "Forbidden",
  description = "You do not have permission to complete this action.",
  requestId,
  backHref = "/dashboard",
  backLabel = "Back to dashboard",
  compact = false,
}: ForbiddenStateProps) {
  const supportAction = getSupportAction();
  const safeRequestId = sanitizeRequestId(requestId ?? null);

  return (
    <section
      className={`rounded-2xl border border-[#d7d4e8] bg-white ${
        compact ? "p-4" : "p-8"
      } shadow-sm`}
      aria-label="Forbidden state"
    >
      <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">
        Rudix Access Control
      </p>
      <h1 className={`${compact ? "text-2xl" : "text-3xl"} mb-2 font-extrabold text-[#2a2640]`}>
        {title}
      </h1>
      <p className="mb-5 text-sm text-[#68647b]">{description}</p>

      {safeRequestId ? (
        <p className="mb-5 rounded-lg bg-[#f5f3ff] px-3 py-2 text-sm text-[#4d4880]">
          Trace ID: <span className="font-semibold">{safeRequestId}</span>
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Link
          href={backHref}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
        >
          {backLabel}
        </Link>

        {supportAction ? (
          <Link
            href={supportAction.href}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            {supportAction.label}
          </Link>
        ) : null}
      </div>
    </section>
  );
}
