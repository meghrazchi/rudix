import { notFound } from "next/navigation";

import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SolutionDetailPage } from "@/components/public/pages/SolutionDetailPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";
import {
  getSolutionAudienceBySlug,
  SOLUTION_AUDIENCES,
  type SolutionSlug,
} from "@/lib/public-site/solutions";

type SolutionDetailRouteProps = {
  params: Promise<{ solutionSlug: string }>;
};

export function generateStaticParams() {
  return SOLUTION_AUDIENCES.map((solution) => ({
    solutionSlug: solution.slug,
  }));
}

export async function generateMetadata({ params }: SolutionDetailRouteProps) {
  const resolvedParams = await params;
  const solution = getSolutionAudienceBySlug(resolvedParams.solutionSlug);

  if (!solution) {
    return buildPublicMetadata({
      title: "Solution | Rudix",
      description: "Department solution details for Rudix workflows.",
      path: "/solutions",
      noIndex: true,
    });
  }

  return buildPublicMetadata({
    title: `${solution.shortLabel} Solution | Rudix`,
    description: solution.summary,
    path: solution.routePath,
  });
}

export default async function SolutionDetailRoute({
  params,
}: SolutionDetailRouteProps) {
  const resolvedParams = await params;
  const solution = getSolutionAudienceBySlug(
    resolvedParams.solutionSlug as SolutionSlug,
  );

  if (!solution) {
    notFound();
  }

  return (
    <PublicMarketingLayout pageLabel={`${solution.shortLabel} solution page`}>
      <SolutionDetailPage solution={solution} />
    </PublicMarketingLayout>
  );
}
