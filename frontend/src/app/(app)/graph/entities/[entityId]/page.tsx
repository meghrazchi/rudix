import { GraphEntityDetailPage } from "@/components/graph/GraphEntityDetailPage";

type GraphEntityRoutePageProps = {
  params: Promise<{
    entityId: string;
  }>;
};

export default async function GraphEntityRoutePage({
  params,
}: GraphEntityRoutePageProps) {
  const { entityId } = await params;

  return <GraphEntityDetailPage entityId={entityId} />;
}
