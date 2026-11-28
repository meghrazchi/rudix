"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Settings2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  DeploymentControlledBadge,
  FieldLabel,
  SaveFeedback,
  ToggleSwitch,
  settingsToForm,
  toList,
  toNullableNumber,
  workspaceDefaultsSchema,
  type SaveState,
  type WorkspaceDefaultsFormValues,
} from "@/components/settings/organization/orgSettingsShared";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getOrganizationSettings,
  isOrganizationEndpointUnavailableError,
  updateOrganizationSettings,
  type getOrganizationCapabilities,
} from "@/lib/api/organization";
import { queryKeys } from "@/lib/api/query";

export function WorkspaceDefaultsSection({
  capabilities,
  isAdmin,
}: {
  capabilities: ReturnType<typeof getOrganizationCapabilities>;
  isAdmin: boolean;
}) {
  const t = useTranslations("settings.organization");

  const [workspaceSaveState, setWorkspaceSaveState] = useState<SaveState>(null);
  const workspaceLastSavedRef = useRef<WorkspaceDefaultsFormValues | null>(
    null,
  );

  const defaultWorkspaceValues: WorkspaceDefaultsFormValues = {
    defaultMemberRole: "member",
    inviteOnly: false,
    allowedEmailDomains: "",
    defaultDocumentVisibility: "private",
    defaultCollection: "",
    retentionDays: "",
    sourceDownload: "admins",
    evaluationAccess: false,
    agenticAccess: false,
    mcpAccess: false,
    analyticsEnabled: true,
  };

  const workspaceForm = useForm<WorkspaceDefaultsFormValues>({
    resolver: zodResolver(workspaceDefaultsSchema),
    defaultValues: defaultWorkspaceValues,
    mode: "onSubmit",
  });

  const settingsQuery = useQuery({
    queryKey: queryKeys.organization.settings,
    queryFn: getOrganizationSettings,
    enabled: capabilities.settingsEnabled && isAdmin,
    retry: false,
  });

  useEffect(() => {
    if (!settingsQuery.data) return;
    const values = settingsToForm(settingsQuery.data);
    workspaceLastSavedRef.current = values;
    workspaceForm.reset(values);
  }, [workspaceForm, settingsQuery.data]);

  const workspaceSaveMutation = useMutation({
    mutationFn: (values: WorkspaceDefaultsFormValues) =>
      updateOrganizationSettings({
        default_member_role: values.defaultMemberRole,
        invite_only: values.inviteOnly,
        allowed_email_domains: toList(values.allowedEmailDomains),
        default_document_visibility: values.defaultDocumentVisibility,
        default_collection: values.defaultCollection || null,
        retention_days: toNullableNumber(values.retentionDays),
        source_download: values.sourceDownload,
        evaluation_access: values.evaluationAccess,
        agentic_access: values.agenticAccess,
        mcp_access: values.mcpAccess,
        analytics_enabled: values.analyticsEnabled,
      }),
    onSuccess: (updated) => {
      const values = settingsToForm(updated);
      workspaceLastSavedRef.current = values;
      workspaceForm.reset(values);
      setWorkspaceSaveState({
        tone: "success",
        message: t("workspace.saved"),
      });
    },
    onError: (error) => {
      setWorkspaceSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveWorkspace(): Promise<void> {
    setWorkspaceSaveState(null);
    const valid = await workspaceForm.trigger();
    if (!valid) return;
    await workspaceSaveMutation.mutateAsync(workspaceForm.getValues());
  }

  function handleDiscardWorkspace(): void {
    const last = workspaceLastSavedRef.current ?? defaultWorkspaceValues;
    workspaceForm.reset(last);
    setWorkspaceSaveState(null);
  }

  const watchedInviteOnly = workspaceForm.watch("inviteOnly");
  const watchedEvalAccess = workspaceForm.watch("evaluationAccess");
  const watchedAgenticAccess = workspaceForm.watch("agenticAccess");
  const watchedMcpAccess = workspaceForm.watch("mcpAccess");
  const watchedAnalyticsEnabled = workspaceForm.watch("analyticsEnabled");

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Workspace defaults section"
    >
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Settings2 size={20} className="text-[#3525cd]" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-[#1b1b24]">
            {t("workspace.title")}
          </h2>
        </div>
        {!capabilities.settingsEnabled && (
          <DeploymentControlledBadge label={t("deploymentControlled")} />
        )}
      </div>

      {!capabilities.settingsEnabled ||
      isOrganizationEndpointUnavailableError(settingsQuery.error) ? (
        <p className="text-sm text-[#777587]">{t("workspace.unavailable")}</p>
      ) : !isAdmin ? (
        <ForbiddenState
          compact
          title={t("workspace.restrictedTitle")}
          description={t("workspace.restrictedDesc")}
          backHref="/dashboard"
          backLabel={t("backToDashboard")}
        />
      ) : settingsQuery.isLoading ? (
        <LoadingState compact title={t("workspace.loading")} />
      ) : settingsQuery.isError ? (
        <ErrorState
          compact
          error={settingsQuery.error}
          description={getApiErrorMessage(settingsQuery.error)}
          onRetry={() => {
            void settingsQuery.refetch();
          }}
        />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <FieldLabel htmlFor="ws-default-role">
                {t("workspace.defaultMemberRole")}
              </FieldLabel>
              <select
                id="ws-default-role"
                {...workspaceForm.register("defaultMemberRole")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="member">{t("workspace.roleMember")}</option>
                <option value="viewer">{t("workspace.roleViewer")}</option>
              </select>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ws-visibility">
                {t("workspace.defaultDocumentVisibility")}
              </FieldLabel>
              <select
                id="ws-visibility"
                {...workspaceForm.register("defaultDocumentVisibility")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="private">
                  {t("workspace.visibilityPrivate")}
                </option>
                <option value="public">
                  {t("workspace.visibilityPublic")}
                </option>
              </select>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ws-source-download">
                {t("workspace.sourceDownload")}
              </FieldLabel>
              <select
                id="ws-source-download"
                {...workspaceForm.register("sourceDownload")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="all">{t("workspace.sourceAll")}</option>
                <option value="admins">{t("workspace.sourceAdmins")}</option>
                <option value="none">{t("workspace.sourceNone")}</option>
              </select>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ws-retention">
                {t("workspace.retentionPolicy")}
              </FieldLabel>
              <select
                id="ws-retention"
                {...workspaceForm.register("retentionDays")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="">{t("workspace.noRetentionLimit")}</option>
                <option value="30">30 days</option>
                <option value="60">60 days</option>
                <option value="90">90 days</option>
                <option value="180">180 days</option>
                <option value="365">365 days</option>
              </select>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ws-allowed-domains">
                {t("workspace.allowedEmailDomains")}
              </FieldLabel>
              <input
                id="ws-allowed-domains"
                {...workspaceForm.register("allowedEmailDomains")}
                placeholder="example.com, partner.org"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="ws-collection">
                {t("workspace.defaultCollection")}
              </FieldLabel>
              <input
                id="ws-collection"
                {...workspaceForm.register("defaultCollection")}
                placeholder="general"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
            </div>
          </div>

          {/* Toggles */}
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="ws-invite-only"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("workspace.inviteOnly")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("workspace.inviteOnlyDesc")}
                </p>
              </div>
              <ToggleSwitch
                id="ws-invite-only"
                checked={watchedInviteOnly}
                onChange={(v) =>
                  workspaceForm.setValue("inviteOnly", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="ws-eval-access"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("workspace.evaluationAccess")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("workspace.evaluationAccessDesc")}
                </p>
              </div>
              <ToggleSwitch
                id="ws-eval-access"
                checked={watchedEvalAccess}
                onChange={(v) =>
                  workspaceForm.setValue("evaluationAccess", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="ws-agentic-access"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("workspace.agenticAccess")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("workspace.agenticAccessDesc")}
                </p>
              </div>
              <ToggleSwitch
                id="ws-agentic-access"
                checked={watchedAgenticAccess}
                onChange={(v) =>
                  workspaceForm.setValue("agenticAccess", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="ws-mcp-access"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("workspace.mcpAccess")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("workspace.mcpAccessDesc")}
                </p>
              </div>
              <ToggleSwitch
                id="ws-mcp-access"
                checked={watchedMcpAccess}
                onChange={(v) =>
                  workspaceForm.setValue("mcpAccess", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="ws-analytics-enabled"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  Analytics enabled
                </label>
                <p className="text-xs text-[#464555]">
                  Allow privacy-aware product analytics for activation and
                  feature usage summaries.
                </p>
              </div>
              <ToggleSwitch
                id="ws-analytics-enabled"
                checked={watchedAnalyticsEnabled}
                onChange={(v) =>
                  workspaceForm.setValue("analyticsEnabled", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-3">
            <SaveFeedback state={workspaceSaveState} />
            <button
              type="button"
              onClick={handleDiscardWorkspace}
              disabled={workspaceSaveMutation.isPending}
              className="rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t("discard")}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleSaveWorkspace();
              }}
              disabled={workspaceSaveMutation.isPending}
              aria-label={t("workspace.saveAriaLabel")}
              className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {workspaceSaveMutation.isPending
                ? t("saving")
                : t("workspace.save")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
