type RetryActionProps = {
  onRetry?: (() => void) | null;
  label?: string;
  disabled?: boolean;
  className?: string;
};

const DEFAULT_RETRY_LABEL = "Retry";

export function RetryAction({
  onRetry,
  label = DEFAULT_RETRY_LABEL,
  disabled = false,
  className,
}: RetryActionProps) {
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
      {label}
    </button>
  );
}
