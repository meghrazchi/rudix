import { useTranslations } from "next-intl";

type RetryActionProps = {
  onRetry?: (() => void) | null;
  label?: string;
  disabled?: boolean;
  className?: string;
};

export function RetryAction({
  onRetry,
  label,
  disabled = false,
  className,
}: RetryActionProps) {
  const t = useTranslations("states");
  if (!onRetry) {
    return null;
  }

  return (
    <button
      type="button"
      onClick={onRetry}
      disabled={disabled}
      className={
        className ??
        "rounded border border-[#cbc5e6] bg-white px-3 py-1 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
      }
    >
      {label ?? t("retry")}
    </button>
  );
}
