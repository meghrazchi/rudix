import { redirect } from "next/navigation";

type Props = {
  params: Promise<{ connectionId: string }>;
};

export default async function SettingsConnectorDetailPage({ params }: Props) {
  const { connectionId } = await params;
  redirect(`/connectors/${decodeURIComponent(connectionId)}`);
}
