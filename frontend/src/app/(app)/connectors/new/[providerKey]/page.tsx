import { ConnectorNewPage } from "@/components/connectors/ConnectorNewPage";

type Props = {
  params: Promise<{ providerKey: string }>;
};

export default async function ConnectorNewRoutePage({ params }: Props) {
  const { providerKey } = await params;
  return <ConnectorNewPage providerKey={decodeURIComponent(providerKey)} />;
}
