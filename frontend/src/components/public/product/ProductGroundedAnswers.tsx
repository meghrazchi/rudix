import { useTranslations } from "next-intl";

import { LandingAnswerPreview } from "@/components/public/landing/LandingAnswerPreview";
import {
  SectionHeading,
  SiteSection,
} from "@/components/public/site/primitives";

export function ProductGroundedAnswers() {
  const t = useTranslations("public.product.groundedAnswers");

  return (
    <SiteSection
      labelledBy="product-answers-title"
      className="bg-site-surface border-site-border border-y"
    >
      <SectionHeading
        id="product-answers-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
        align="center"
      />
      <div className="mt-12">
        <LandingAnswerPreview />
      </div>
    </SiteSection>
  );
}
