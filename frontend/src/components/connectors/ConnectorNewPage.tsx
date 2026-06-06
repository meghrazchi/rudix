"use client";

import { ConnectorSetupPage } from "@/components/connectors/ConnectorSetupPage";

type Props = {
  providerKey: string;
};

export function ConnectorNewPage({ providerKey }: Props) {
  return <ConnectorSetupPage providerKey={providerKey} />;
}
