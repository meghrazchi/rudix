import { useTranslations } from "next-intl";

type LoadingStateProps = {
  title?: string;
  description?: string;
  compact?: boolean;
  className?: string;
};

export function LoadingState({
  title,
  description,
  compact = false,
  className,
}: LoadingStateProps) {
  const t = useTranslations("states");
  return (
    <section
      role="status"
      aria-live="polite"
      aria-label={t("loading.aria")}
      className={
        className ??
        `rounded-lg border border-[#e4e1f2] bg-[#faf9ff] ${
          compact ? "px-3 py-2" : "px-4 py-4"
        } text-sm text-[#5f5b72]`
      }
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={`inline-block rounded-full bg-[#3525cd]/30 ${compact ? "h-2 w-2" : "h-2.5 w-2.5"} animate-pulse`}
        />
        <p className={compact ? "font-medium" : "font-semibold"}>
          {title ?? t("loading.title")}
        </p>
      </div>
      {description ? <p className="mt-1 ml-4">{description}</p> : null}
    </section>
  );
}
