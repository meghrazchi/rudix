import Link from "next/link";
import { useTranslations } from "next-intl";

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
  title,
  description,
  requestId,
  backHref = "/dashboard",
  backLabel,
  compact = false,
}: ForbiddenStateProps) {
  const t = useTranslations("states");
  const supportAction = getSupportAction();
  const safeRequestId = sanitizeRequestId(requestId ?? null);

  return (
    <section
      className={`rounded-2xl border border-[#d7d4e8] bg-white ${
        compact ? "p-4" : "p-8"
      } shadow-sm`}
      aria-label={t("forbidden.aria")}
    >
      <p className="mb-2 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
        {t("forbidden.eyebrow")}
      </p>
      <h1
        className={`${compact ? "text-2xl" : "text-3xl"} mb-2 font-extrabold text-[#2a2640]`}
      >
        {title ?? t("forbidden.title")}
      </h1>
      <p className="mb-5 text-sm text-[#68647b]">
        {description ?? t("forbidden.description")}
      </p>

      {safeRequestId ? (
        <p className="mb-5 rounded-lg bg-[#f5f3ff] px-3 py-2 text-sm text-[#4d4880]">
          {t("traceId")} <span className="font-semibold">{safeRequestId}</span>
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Link
          href={backHref}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
        >
          {backLabel ?? t("forbidden.backLabel")}
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
