import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ClientPortalSolutionPage } from "@/components/public/pages/ClientPortalSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Client Portal Solution | Rudix",
  description:
    "Deploy a scoped AI Q&A layer over your client-facing documentation. Give customers citation-backed answers to onboarding, implementation, and support questions without overloading your team.",
  path: "/solutions/client-portal",
});

export default function ClientPortalSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Client Portal solution page">
      <ClientPortalSolutionPage />
    </PublicMarketingLayout>
  );
}
