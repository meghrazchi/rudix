import type { Metadata } from "next";

import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";

/**
 * Document-level metadata shared by both root layouts (`app/[locale]` and
 * `app/(app)`). Pages extend it through `generateMetadata`.
 */
export const ROOT_METADATA: Metadata = {
  metadataBase: new URL(resolvePublicSiteBaseUrl()),
  title: {
    default: "Rudix",
    template: "%s | Rudix",
  },
  description:
    "AI document Q&A with cited answers from your company documents.",
  icons: {
    icon: "/brand/rudix-mark.svg",
    shortcut: "/brand/rudix-mark.svg",
    apple: "/brand/rudix-mark.svg",
  },
};
