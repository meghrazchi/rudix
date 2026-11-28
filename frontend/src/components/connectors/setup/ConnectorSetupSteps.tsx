"use client";

import { useTranslations } from "next-intl";
import type { WizardStepProps } from "@/components/connectors/wizard/types";
import { ProviderCapabilityBadges } from "@/components/connectors/ProviderCapabilityBadges";
import { type ProviderSummary } from "@/lib/api/connector-providers";
import { ConnectorSetupState } from "@/components/connectors/setup/types";
import {
  configSummary,
  externalAccountPlaceholder,
  fieldLabel,
  fieldPlaceholder,
  toStringArray,
  validateConfigField,
} from "@/components/connectors/setup/configHelpers";

export function BasicStep({
  state,
  onChange,
  provider,
}: WizardStepProps<ConnectorSetupState> & { provider: ProviderSummary }) {
  const t = useTranslations("connectors.setup");
  return (
    <div className="grid gap-5 lg:grid-cols-[1.3fr,0.9fr]">
      <div className="space-y-5">
        <div>
          <label
            className="block text-sm font-semibold text-[#2a2640]"
            htmlFor="connector-display-name"
          >
            {t("basics.connectionName")}
          </label>
          <input
            id="connector-display-name"
            type="text"
            value={state.display_name}
            onChange={(event) => onChange({ display_name: event.target.value })}
            className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
            placeholder={t("basics.namePlaceholder", {
              provider: provider.display_name,
            })}
          />
        </div>

        <div>
          <label
            className="block text-sm font-semibold text-[#2a2640]"
            htmlFor="connector-external-account-id"
          >
            {provider.key === "microsoft-sharepoint-onedrive"
              ? t("basics.tenantAccountId")
              : t("basics.externalAccountId")}
          </label>
          <p className="mt-1 text-xs text-[#6a6780]">
            {provider.key === "microsoft-sharepoint-onedrive"
              ? t("basics.tenantHelper")
              : t("basics.accountHelper")}
          </p>
          <input
            id="connector-external-account-id"
            type="text"
            value={state.external_account_id}
            onChange={(event) =>
              onChange({ external_account_id: event.target.value })
            }
            className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
            placeholder={externalAccountPlaceholder(provider.key)}
          />
        </div>
      </div>

      <aside className="rounded-2xl border border-[#d7d4e8] bg-[#faf9fe] p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          {t("basics.providerOverview")}
        </h3>
        <p className="mt-1 text-sm text-[#68647b]">
          {t.has(`providers.${provider.key}.description`)
            ? t(`providers.${provider.key}.description`)
            : (provider.capabilities.notes ?? t("basics.providerFallback"))}
        </p>
        <div className="mt-3">
          <ProviderCapabilityBadges provider={provider} />
        </div>
        <div className="mt-4 rounded-xl bg-white p-3 text-sm text-[#4b4860]">
          <div className="font-semibold text-[#2a2640]">
            {t("basics.authModel")}
          </div>
          <div className="mt-1 capitalize">
            {provider.capabilities.auth_type.replace(/_/g, " ")}
          </div>
        </div>
      </aside>
    </div>
  );
}

export function ScopeStep({
  state,
  onChange,
  provider,
}: WizardStepProps<ConnectorSetupState> & { provider: ProviderSummary }) {
  const t = useTranslations("connectors.setup");
  const fields = provider.config_schema.properties ?? {};
  const required = new Set(provider.config_schema.required ?? []);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr,0.9fr]">
      <div className="space-y-4">
        {Object.keys(fields).length === 0 && (
          <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-4 text-sm text-[#6a6780]">
            {t("scope.noFields")}
          </div>
        )}

        {Object.entries(fields).map(([name, field]) => {
          const value = state.config_values[name];
          const error = validateConfigField(
            field,
            value ?? "",
            required.has(name),
          );
          const isBoolean = field.type === "boolean";
          const isArray = field.type === "array";
          const isTextArea = name === "jql_filter" || name === "cql_filter";
          const localizedFieldKey = `fields.${provider.key}.${name}`;
          const localizedLabel = t.has(`${localizedFieldKey}.label`)
            ? t(`${localizedFieldKey}.label`)
            : fieldLabel(name, field);
          const localizedDescription = t.has(`${localizedFieldKey}.description`)
            ? t(`${localizedFieldKey}.description`)
            : field.description;

          return (
            <div key={name}>
              <label
                className="block text-sm font-semibold text-[#2a2640]"
                htmlFor={`connector-config-${name}`}
              >
                {localizedLabel}
                {required.has(name) && (
                  <span className="ml-1 text-[#c2410c]">*</span>
                )}
              </label>
              {localizedDescription && (
                <p className="mt-1 text-xs text-[#6a6780]">
                  {localizedDescription}
                </p>
              )}
              {isBoolean ? (
                <label className="mt-2 inline-flex items-center gap-3 rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5">
                  <input
                    id={`connector-config-${name}`}
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(event) =>
                      onChange({
                        config_values: {
                          ...state.config_values,
                          [name]: event.target.checked,
                        },
                      })
                    }
                    className="h-4 w-4 rounded border-[#bfb9d8] text-[#3525cd] focus:ring-[#3525cd]"
                  />
                  <span className="text-sm text-[#2a2640]">
                    {localizedDescription ??
                      t("scope.enableField", { field: localizedLabel })}
                  </span>
                </label>
              ) : (
                <textarea
                  id={`connector-config-${name}`}
                  rows={isTextArea ? 4 : isArray ? 2 : 1}
                  value={typeof value === "string" ? value : ""}
                  onChange={(event) =>
                    onChange({
                      config_values: {
                        ...state.config_values,
                        [name]: event.target.value,
                      },
                    })
                  }
                  placeholder={
                    t.has(`${localizedFieldKey}.placeholder`)
                      ? t(`${localizedFieldKey}.placeholder`)
                      : fieldPlaceholder(name, field)
                  }
                  className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
                />
              )}
              {isArray &&
                typeof value === "string" &&
                value.trim().length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {toStringArray(value).map((item) => (
                      <span
                        key={item}
                        className="rounded-full bg-[#ece8ff] px-2.5 py-1 text-xs font-semibold text-[#3525cd]"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              {error && (
                <p className="mt-1 text-xs text-[#b42318]">
                  {t(`validation.${error}`)}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <aside className="space-y-4 rounded-2xl border border-[#d7d4e8] bg-[#faf9fe] p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          {t("scope.title")}
        </h3>
        <div className="space-y-2">
          {configSummary(
            provider,
            state.config_values,
            t("common.enabled"),
            t("scope.aclSummary"),
          ).length === 0 && (
            <p className="text-sm text-[#68647b]">{t("scope.noneSelected")}</p>
          )}
          {configSummary(
            provider,
            state.config_values,
            t("common.enabled"),
            t("scope.aclSummary"),
          ).map((item) => (
            <div
              key={item}
              className="rounded-xl bg-white px-3 py-2 text-sm text-[#4b4860]"
            >
              {item}
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-[#ece8ff] bg-white p-3 text-sm text-[#4b4860]">
          {t("scope.savedDescription")}
        </div>
      </aside>
    </div>
  );
}

export function ReviewStep({
  state,
  provider,
}: WizardStepProps<ConnectorSetupState> & { provider: ProviderSummary }) {
  const t = useTranslations("connectors.setup");
  const scope = configSummary(
    provider,
    state.config_values,
    t("common.enabled"),
    t("scope.aclSummary"),
  );

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr,0.9fr]">
      <div className="space-y-4">
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            {t("basics.connectionName")}
          </div>
          <div className="mt-1 text-lg font-bold text-[#2a2640]">
            {state.display_name || t("review.untitled")}
          </div>
        </div>

        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            {t("review.sourceScope")}
          </div>
          {scope.length === 0 ? (
            <div className="mt-2 text-sm text-[#68647b]">
              {t("review.noFilter")}
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              {scope.map((item) => (
                <span
                  key={item}
                  className="rounded-full bg-[#ece8ff] px-3 py-1.5 text-xs font-semibold text-[#3525cd]"
                >
                  {item}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <aside className="rounded-2xl border border-[#d7d4e8] bg-[#faf9fe] p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          {t("review.nextTitle")}
        </h3>
        <p className="mt-1 text-sm text-[#68647b]">
          {provider.capabilities.auth_type === "oauth2"
            ? t("review.oauthNext")
            : t("review.directNext")}
        </p>
        <div className="mt-4 rounded-xl bg-white p-3 text-sm text-[#4b4860]">
          {t("review.selectedAuthModel")}:{" "}
          <span className="font-semibold capitalize">
            {provider.capabilities.auth_type.replace(/_/g, " ")}
          </span>
        </div>
      </aside>
    </div>
  );
}
