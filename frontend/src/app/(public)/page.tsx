import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { LandingPage } from "@/components/public/pages/LandingPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Enterprise RAG Infrastructure",
  description:
    "Rudix is a production-ready enterprise RAG platform with secure ingestion, grounded chat, evaluation analytics, and pipeline observability.",
  path: "/",
});

export default function Home() {
  return (
    <PublicMarketingLayout pageLabel="Rudix public landing page">
      <LandingPage />
    </PublicMarketingLayout>
  );
}
