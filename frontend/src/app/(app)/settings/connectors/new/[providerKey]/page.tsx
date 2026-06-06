import { ConnectorSetupPage } from "@/components/connectors/ConnectorSetupPage";

type Props = {
  params: Promise<{ providerKey: string }>;
};

export default async function SettingsConnectorNewPage({ params }: Props) {
  const { providerKey } = await params;
  return <ConnectorSetupPage providerKey={decodeURIComponent(providerKey)} />;
}
