import { ConnectorConnectionDetailPage } from "@/components/connectors/ConnectorConnectionDetailPage";

type Props = {
  params: Promise<{ connectionId: string }>;
};

export default async function ConnectorDetailRoutePage({ params }: Props) {
  const { connectionId } = await params;
  return (
    <ConnectorConnectionDetailPage
      connectionId={decodeURIComponent(connectionId)}
    />
  );
}
