"use client";

import { useMemo, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ConnectorWizard } from "@/components/connectors/wizard/ConnectorWizard";
import type { ConnectorWizardConfig } from "@/components/connectors/wizard/types";
import type { WizardStepProps } from "@/components/connectors/wizard/types";
import { ProviderCapabilityBadges } from "@/components/connectors/ProviderCapabilityBadges";
import { getApiErrorMessage, type ApiClientError } from "@/lib/api/errors";
import {
  beginConnectorOAuthConnect,
  createConnectorConnection,
} from "@/lib/api/connectors";
import {
  getProvider,
  type ProviderSummary,
} from "@/lib/api/connector-providers";
import { queryKeys } from "@/lib/api/query";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { ConnectorSetupState } from "@/components/connectors/setup/types";
import {
  buildConfigFieldState,
  buildProviderConfig,
  validateConfigField,
} from "@/components/connectors/setup/configHelpers";
import {
  BasicStep,
  ReviewStep,
  ScopeStep,
} from "@/components/connectors/setup/ConnectorSetupSteps";
import { PermissionReviewStep } from "@/components/connectors/setup/PermissionReviewStep";
import { ConfluenceSetupGuide } from "@/components/connectors/setup/ConfluenceSetupGuide";
import { GoogleDriveSetupGuide } from "@/components/connectors/setup/GoogleDriveSetupGuide";
import { NotionSetupGuide } from "@/components/connectors/setup/NotionSetupGuide";
import { MicrosoftSharePointOneDriveSetupGuide } from "@/components/connectors/setup/MicrosoftSetupGuide";

type Props = {
  providerKey: string;
};

function WizardShell({ provider }: { provider: ProviderSummary }) {
  const t = useTranslations("connectors.setup");
  const router = useRouter();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const initialState = useMemo<ConnectorSetupState>(
    () => ({
      display_name: provider.display_name,
      external_account_id: "",
      config_values: buildConfigFieldState(provider.config_schema),
      confirmed: false,
    }),
    [provider],
  );

  async function handleComplete(state: ConnectorSetupState): Promise<void> {
    setSubmitting(true);
    setErrorMessage(null);
    const config = buildProviderConfig(
      provider.config_schema,
      state.config_values,
    );
    try {
      if (provider.capabilities.auth_type === "oauth2") {
        const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
        const result = await beginConnectorOAuthConnect({
          provider_key: provider.key,
          redirect_uri: `${apiUrl}/connectors/oauth/callback`,
          display_name: state.display_name.trim() || provider.display_name,
          external_account_id: state.external_account_id.trim() || null,
          config,
        });
        window.location.assign(result.authorization_url);
        return;
      }

      const created = await createConnectorConnection({
        provider_key: provider.key,
        display_name: state.display_name.trim() || provider.display_name,
        external_account_id: state.external_account_id.trim() || null,
        config,
      });
      router.push(`/connectors/${created.id}`);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  const steps: ConnectorWizardConfig<ConnectorSetupState>["steps"] = [
    {
      key: "basics",
      label: t("steps.basics"),
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <BasicStep {...props} provider={provider} />
      ),
      canProceed: (state: ConnectorSetupState) =>
        state.display_name.trim().length > 0,
    },
    {
      key: "scope",
      label: t("steps.scope"),
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <ScopeStep {...props} provider={provider} />
      ),
      canProceed: (state: ConnectorSetupState) =>
        Object.entries(provider.config_schema.properties ?? {}).every(
          ([name, field]) => {
            const required = (provider.config_schema.required ?? []).includes(
              name,
            );
            return !validateConfigField(
              field,
              state.config_values[name] ?? "",
              required,
            );
          },
        ),
    },
    {
      key: "permissions",
      label: t("steps.permissions"),
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <PermissionReviewStep
          {...props}
          provider={provider}
          scopeValues={props.state.config_values}
        />
      ),
      canProceed: (state: ConnectorSetupState) => state.confirmed === true,
    },
    {
      key: "review",
      label: t("steps.review"),
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <ReviewStep {...props} provider={provider} />
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {errorMessage && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
          {errorMessage}
        </div>
      )}
      <ConnectorWizard
        config={{
          providerKey: provider.key,
          displayName: provider.display_name,
          initialState,
          steps,
          onComplete: handleComplete,
          onCancel: () => router.push("/connectors"),
        }}
      />
      {submitting && (
        <div className="text-sm text-[#6a6780]">{t("submitting")}</div>
      )}
    </div>
  );
}

function ProviderLoader({ providerKey }: Props) {
  const t = useTranslations("connectors.setup");
  const router = useRouter();
  const providerQuery = useQuery({
    queryKey: queryKeys.connectorProvider(providerKey),
    queryFn: () => getProvider(providerKey),
  });

  if (providerQuery.isLoading) {
    return (
      <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-6 text-sm text-[#68647b]">
        {t("loading")}
      </div>
    );
  }

  if (providerQuery.isError || !providerQuery.data) {
    const error = providerQuery.error as ApiClientError | null;
    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-900">
          <div className="font-semibold">{t("loadErrorTitle")}</div>
          <p className="mt-1">
            {error ? getApiErrorMessage(error) : t("loadErrorDescription")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push("/connectors")}
          className="rounded-xl border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#3525cd]"
        >
          {t("backToConnectors")}
        </button>
      </div>
    );
  }

  const provider = providerQuery.data;
  const authLabel = provider.capabilities.auth_type.replace(/_/g, " ");
  const description =
    (t.has(`providers.${provider.key}.description`)
      ? t(`providers.${provider.key}.description`)
      : provider.capabilities.notes) ?? t("providerDescriptionFallback");

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("eyebrow")}
        </p>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              {t("connectTitle", { provider: provider.display_name })}
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">{description}</p>
          </div>
          <div className="rounded-xl bg-[#faf9fe] px-4 py-3 text-sm text-[#4b4860]">
            <div className="font-semibold text-[#2a2640]">{t("authType")}</div>
            <div className="capitalize">{authLabel}</div>
          </div>
        </div>
        <div className="mt-4">
          <ProviderCapabilityBadges provider={provider} />
        </div>
      </header>

      {provider.key === "confluence" && <ConfluenceSetupGuide />}
      {provider.key === "google_drive" && <GoogleDriveSetupGuide />}
      {provider.key === "microsoft-sharepoint-onedrive" && (
        <MicrosoftSharePointOneDriveSetupGuide />
      )}
      {provider.key === "notion" && <NotionSetupGuide />}

      <WizardShell provider={provider} />
    </section>
  );
}

export function ConnectorSetupPage({ providerKey }: Props) {
  const client = useMemo(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false } },
      }),
    [],
  );

  return (
    <QueryClientProvider client={client}>
      <ProviderLoader providerKey={providerKey} />
    </QueryClientProvider>
  );
}
