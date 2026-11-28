import { useTranslations } from "next-intl";

import { RetryAction } from "@/components/states/RetryAction";
import { sanitizeRequestId } from "@/lib/forbidden";

type RateLimitStateProps = {
  title?: string;
  description?: string;
  requestId?: string | null;
  onRetry?: (() => void) | null;
  compact?: boolean;
  retryLabel?: string;
};

export function RateLimitState({
  title,
  description,
  requestId,
  onRetry,
  compact = false,
  retryLabel,
}: RateLimitStateProps) {
  const t = useTranslations("states");
  const safeRequestId = sanitizeRequestId(requestId ?? null);

  return (
    <section
      role="alert"
      aria-live="assertive"
      aria-label={t("rateLimit.aria")}
      className={`rounded-lg border border-amber-200 bg-amber-50 ${
        compact ? "px-3 py-2" : "px-4 py-4"
      } text-amber-900`}
    >
      <p
        className={
          compact ? "text-sm font-semibold" : "text-base font-semibold"
        }
      >
        {title ?? t("rateLimit.title")}
      </p>
      <p className={`${compact ? "mt-1 text-xs" : "mt-1 text-sm"}`}>
        {description ?? t("rateLimit.description")}
      </p>
      {safeRequestId ? (
        <p className="mt-2 text-xs">
          {t("traceId")} <span className="font-semibold">{safeRequestId}</span>
        </p>
      ) : null}
      <div className="mt-2">
        <RetryAction
          onRetry={onRetry}
          label={retryLabel}
          className="rounded border border-amber-300 bg-white px-3 py-1 text-xs font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
        />
      </div>
    </section>
  );
}
