"use client";

import { useRouter } from "next/navigation";
import { JiraWizard } from "@/components/connectors/jira/JiraWizard";
import type { JiraWizardState } from "@/components/connectors/jira/JiraWizard.types";

type Props = {
  providerKey: string;
};

export function ConnectorNewPage({ providerKey }: Props) {
  const router = useRouter();

  function handleCancel() {
    router.push("/connectors");
  }

  if (providerKey === "jira") {
    return (
      <div className="p-8 flex justify-center items-start min-h-full">
        <JiraWizard
          onComplete={async (_state: JiraWizardState) => {
            // In production: POST /connectors/oauth/connect → credential vault → create connection
            // Then redirect to the new connection detail page.
            router.push("/connectors");
          }}
          onCancel={handleCancel}
        />
      </div>
    );
  }

  // Fallback for providers that don't have a wizard yet.
  return (
    <div className="p-8 max-w-lg mx-auto text-center mt-16">
      <div className="w-16 h-16 bg-[#f5f2ff] rounded-full flex items-center justify-center mx-auto mb-4">
        <span className="material-symbols-outlined text-[32px] text-[#3525cd]">
          construction
        </span>
      </div>
      <h2 className="text-xl font-semibold text-[#1b1b24] mb-2">
        Wizard coming soon
      </h2>
      <p className="text-sm text-[#464555] mb-6">
        The setup wizard for{" "}
        <span className="font-semibold capitalize">{providerKey.replace("_", " ")}</span>{" "}
        is not yet available.
      </p>
      <button
        type="button"
        onClick={handleCancel}
        className="px-6 py-2.5 border border-[#777587] text-[#464555] rounded-lg text-sm font-semibold hover:bg-[#f5f2ff] transition-colors"
      >
        Back to Connectors
      </button>
    </div>
  );
}
