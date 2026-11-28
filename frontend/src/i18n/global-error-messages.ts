import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE_NAME,
  isValidLocale,
  type SupportedLocale,
} from "@/i18n/routing";

/**
 * Strings for `app/global-error.tsx`. That boundary replaces the root layout,
 * so no NextIntlClientProvider exists and the message catalogues are not
 * loaded: these few strings are bundled directly instead.
 */
export type GlobalErrorMessages = {
  title: string;
  description: string;
  retry: string;
  home: string;
  reference: string;
};

export const GLOBAL_ERROR_MESSAGES: Record<
  SupportedLocale,
  GlobalErrorMessages
> = {
  en: {
    title: "Unable to render this page",
    description:
      "A runtime error interrupted rendering. You can retry this view or go back to the homepage.",
    retry: "Retry",
    home: "Back to homepage",
    reference: "Error reference",
  },
  de: {
    title: "Seite kann nicht angezeigt werden",
    description:
      "Ein Laufzeitfehler hat die Darstellung unterbrochen. Sie können es erneut versuchen oder zur Startseite zurückkehren.",
    retry: "Erneut versuchen",
    home: "Zur Startseite",
    reference: "Fehlerreferenz",
  },
  es: {
    title: "No se puede mostrar esta página",
    description:
      "Un error en tiempo de ejecución interrumpió la carga. Puedes reintentar o volver al inicio.",
    retry: "Reintentar",
    home: "Volver al inicio",
    reference: "Referencia del error",
  },
  fr: {
    title: "Impossible d’afficher cette page",
    description:
      "Une erreur d’exécution a interrompu l’affichage. Vous pouvez réessayer ou revenir à l’accueil.",
    retry: "Réessayer",
    home: "Retour à l’accueil",
    reference: "Référence de l’erreur",
  },
  ar: {
    title: "تعذّر عرض هذه الصفحة",
    description:
      "أدّى خطأ أثناء التشغيل إلى مقاطعة العرض. يمكنك إعادة المحاولة أو العودة إلى الصفحة الرئيسية.",
    retry: "إعادة المحاولة",
    home: "العودة إلى الصفحة الرئيسية",
    reference: "مرجع الخطأ",
  },
  fa: {
    title: "نمایش این صفحه ممکن نیست",
    description:
      "یک خطای زمان اجرا نمایش را متوقف کرد. می‌توانید دوباره تلاش کنید یا به صفحه اصلی برگردید.",
    retry: "تلاش دوباره",
    home: "بازگشت به صفحه اصلی",
    reference: "شناسه خطا",
  },
};

function cookieLocale(cookieString: string): string | undefined {
  for (const part of cookieString.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === LOCALE_COOKIE_NAME) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

/**
 * Locale for the global error boundary: the `<html lang>` of the page that
 * failed, else the NEXT_LOCALE cookie, else English.
 */
export function resolveGlobalErrorLocale(
  htmlLang: string | null | undefined,
  cookieString: string | null | undefined,
): SupportedLocale {
  const fromHtml = (htmlLang ?? "").trim().toLowerCase().split("-")[0];
  if (isValidLocale(fromHtml)) return fromHtml;
  const fromCookie = cookieLocale(cookieString ?? "");
  if (isValidLocale(fromCookie)) return fromCookie;
  return DEFAULT_LOCALE;
}
