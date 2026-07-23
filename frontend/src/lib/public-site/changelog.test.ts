import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import faMessages from "@/i18n/messages/fa.json";
import { getPublicChangelogEntries } from "@/lib/public-site/changelog";

describe("public changelog localization", () => {
  it("loads fully localized Persian release notes from next-intl", () => {
    const t = createTranslator({
      locale: "fa",
      messages: faMessages,
      namespace: "public.changelog",
    });
    const entries = t.raw("releases");

    expect(entries[0]).toMatchObject({
      date: "۳۰ خرداد ۱۴۰۵",
      milestone: "بهبود محصول و امور حقوقی",
    });
    expect(entries[0]?.summary).toContain("یادداشت‌های انتشار عمومی");
    expect(entries[0]?.categories[0]?.items[0]).toContain("مسیر عمومی");
    expect(entries[0]?.links[0]?.label).toBe("مرور نمای کلی محصول");
    expect(entries[1]?.milestone).toBe("ارزیابی و مشاهده‌پذیری");
    expect(entries[2]?.milestone).toBe("امنیت و شروع به کار");
  });

  it("keeps English as the fallback for other locales", () => {
    expect(getPublicChangelogEntries()[0]?.date).toBe("June 20, 2026");
  });
});
