"use client";

import { useLayoutEffect, type ReactNode } from "react";

import { getLocaleDirection } from "@/i18n/direction";
import type { SupportedLocale } from "@/i18n/routing";
import { getHtmlLang } from "@/lib/i18n-format";

type LocaleDocumentAttributesProps = {
  children: ReactNode;
  locale: SupportedLocale;
};

export function LocaleDocumentAttributes({
  children,
  locale,
}: LocaleDocumentAttributesProps) {
  const direction = getLocaleDirection(locale);
  const language = getHtmlLang(locale);

  useLayoutEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = direction;
  }, [direction, language]);

  return (
    <div className="contents" lang={language} dir={direction}>
      {children}
    </div>
  );
}
