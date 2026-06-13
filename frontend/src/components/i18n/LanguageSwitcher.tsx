"use client";

import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";

import { usePathname, useRouter } from "@/i18n/navigation";
import { SUPPORTED_LOCALES, type SupportedLocale } from "@/i18n/routing";

type LanguageSwitcherVariant = "select" | "buttons";

type LanguageSwitcherProps = {
  variant?: LanguageSwitcherVariant;
  className?: string;
};

const LOCALE_FLAGS: Record<SupportedLocale, string> = {
  en: "🇬🇧",
  de: "🇩🇪",
  es: "🇪🇸",
  fr: "🇫🇷",
};

export function LanguageSwitcher({
  variant = "select",
  className,
}: LanguageSwitcherProps) {
  const t = useTranslations("languageSwitcher");
  const currentLocale = useLocale() as SupportedLocale;
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  function applyLocale(locale: SupportedLocale): void {
    if (locale === currentLocale) return;

    startTransition(() => {
      router.replace(pathname, { locale });
    });
  }

  if (variant === "buttons") {
    return (
      <div role="group" aria-label={t("ariaLabel")} className={className}>
        {SUPPORTED_LOCALES.map((locale) => (
          <button
            key={locale}
            type="button"
            lang={locale}
            disabled={isPending}
            aria-current={locale === currentLocale ? "true" : undefined}
            onClick={() => applyLocale(locale)}
            className={[
              "rounded px-2 py-1 text-xs font-semibold transition-colors",
              locale === currentLocale
                ? "bg-[#3525cd] text-white"
                : "text-[#5d58a8] hover:bg-[#ece9ff]",
              isPending ? "cursor-wait opacity-60" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <span aria-hidden="true">{LOCALE_FLAGS[locale]}</span>{" "}
            {locale.toUpperCase()}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className={className}>
      <label htmlFor="language-switcher" className="sr-only">
        {t("ariaLabel")}
      </label>
      <select
        id="language-switcher"
        value={currentLocale}
        disabled={isPending}
        onChange={(event) => applyLocale(event.target.value as SupportedLocale)}
        aria-label={t("ariaLabel")}
        className={[
          "rounded-lg border border-[#d2cee6] bg-white px-2 py-1 text-xs font-medium text-[#4e5160] transition",
          "focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none",
          isPending ? "cursor-wait opacity-60" : "cursor-pointer",
        ].join(" ")}
      >
        {SUPPORTED_LOCALES.map((locale) => (
          <option key={locale} value={locale} lang={locale}>
            {LOCALE_FLAGS[locale]} {t(locale)}
          </option>
        ))}
      </select>
    </div>
  );
}
