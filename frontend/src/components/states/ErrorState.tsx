import { useTranslations } from "next-intl";

import { NetworkErrorState } from "@/components/states/NetworkErrorState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { RetryAction } from "@/components/states/RetryAction";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { extractRequestIdFromError, sanitizeRequestId } from "@/lib/forbidden";

type ErrorStateProps = {
  title?: string;
  description?: string;
  error?: unknown;
  requestId?: string | null;
  onRetry?: (() => void) | null;
  retryLabel?: string;
  compact?: boolean;
};

function resolveTitle(params: {
  title?: string;
  error?: unknown;
  t: (key: string) => string;
}): string {
  if (params.title) {
    return params.title;
  }

  if (isApiClientError(params.error)) {
    if (params.error.status === 409) {
      return params.t("error.conflict");
    }
    if (params.error.status === 401) {
      return params.t("error.invalidSession");
    }
  }

  return params.t("error.unableToLoad");
}

function resolveDescription(params: {
  description?: string;
  error?: unknown;
}): string {
  if (params.description) {
    return params.description;
  }
  return getApiErrorMessage(params.error);
}

export function ErrorState({
  title,
  description,
  error,
  requestId,
  onRetry,
  retryLabel,
  compact = false,
}: ErrorStateProps) {
  const t = useTranslations("states");
  if (isApiClientError(error) && error.status === 0) {
    return (
      <NetworkErrorState
        onRetry={onRetry}
        retryLabel={retryLabel}
        compact={compact}
      />
    );
  }

  if (isApiClientError(error) && error.status === 429) {
    return (
      <RateLimitState
        title={title}
        description={description}
        requestId={requestId ?? extractRequestIdFromError(error)}
        onRetry={onRetry}
        retryLabel={retryLabel}
        compact={compact}
      />
    );
  }

  const resolvedTitle = resolveTitle({ title, error, t });
  const resolvedDescription = resolveDescription({ description, error });
  const safeRequestId = sanitizeRequestId(
    requestId ?? extractRequestIdFromError(error),
  );

  return (
    <section
      role="alert"
      aria-live="assertive"
      aria-label={t("error.aria")}
      className={`rounded-lg border border-rose-200 bg-rose-50 ${
        compact ? "px-3 py-2" : "px-4 py-4"
      } text-rose-900`}
    >
      <p
        className={
          compact ? "text-sm font-semibold" : "text-base font-semibold"
        }
      >
        {resolvedTitle}
      </p>
      <p className={`${compact ? "mt-1 text-xs" : "mt-1 text-sm"}`}>
        {resolvedDescription}
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
          className="rounded border border-rose-300 bg-white px-3 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
        />
      </div>
    </section>
  );
}
