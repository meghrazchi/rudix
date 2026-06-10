import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ContactDemoPage } from "@/components/public/pages/ContactDemoPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Contact & Demo | Rudix",
  description:
    "Request a Rudix demo or contact the team to discuss document AI workflows, governance needs, and rollout planning.",
  path: "/contact",
});

export default function ContactPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix contact page">
      <ContactDemoPage />
    </PublicMarketingLayout>
  );
}
