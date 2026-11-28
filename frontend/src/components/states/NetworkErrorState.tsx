import { useTranslations } from "next-intl";

import { RetryAction } from "@/components/states/RetryAction";

type NetworkErrorStateProps = {
  onRetry?: (() => void) | null;
  retryLabel?: string;
  compact?: boolean;
};

export function NetworkErrorState({
  onRetry,
  retryLabel,
  compact = false,
}: NetworkErrorStateProps) {
  const t = useTranslations("states");
  return (
    <section
      role="alert"
      aria-live="assertive"
      aria-label={t("network.aria")}
      className={`rounded-lg border border-amber-200 bg-amber-50 ${
        compact ? "px-3 py-2" : "px-4 py-4"
      } text-amber-900`}
    >
      <p
        className={
          compact ? "text-sm font-semibold" : "text-base font-semibold"
        }
      >
        {t("network.title")}
      </p>
      <p className={compact ? "mt-1 text-xs" : "mt-1 text-sm"}>
        {t("network.description")}
      </p>
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
