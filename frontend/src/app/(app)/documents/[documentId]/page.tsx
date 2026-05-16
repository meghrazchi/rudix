import { DocumentDetailPage } from "@/components/documents/DocumentDetailPage";

type DocumentDetailRoutePageProps = {
  params: {
    documentId: string;
  };
};

export default function DocumentDetailRoutePage({ params }: DocumentDetailRoutePageProps) {
  return <DocumentDetailPage documentId={params.documentId} />;
}
