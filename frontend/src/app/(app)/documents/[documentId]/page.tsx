import { DocumentDetailPage } from "@/components/documents/DocumentDetailPage";

type DocumentDetailRoutePageProps = {
  params: Promise<{
    documentId: string;
  }>;
};

export default async function DocumentDetailRoutePage({
  params,
}: DocumentDetailRoutePageProps) {
  const { documentId } = await params;

  return <DocumentDetailPage key={documentId} documentId={documentId} />;
}
