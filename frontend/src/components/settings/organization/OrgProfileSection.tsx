"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Building2, Copy, CopyCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm, useWatch } from "react-hook-form";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  DeploymentControlledBadge,
  FieldLabel,
  ReadOnlyField,
  SaveFeedback,
  formatDate,
  orgProfileSchema,
  profileToForm,
  toList,
  type OrgProfileFormValues,
  type SaveState,
} from "@/components/settings/organization/orgSettingsShared";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getOrganizationProfile,
  isOrganizationEndpointUnavailableError,
  updateOrganizationProfile,
  type getOrganizationCapabilities,
} from "@/lib/api/organization";
import { queryKeys } from "@/lib/api/query";
import { orgAvatarColor, orgInitials } from "@/lib/workspace";

type Session = {
  organizationId?: string | null;
  organizationName?: string | null;
} | null;

export function OrgProfileSection({
  capabilities,
  isAdmin,
  session,
  billingHref,
}: {
  capabilities: ReturnType<typeof getOrganizationCapabilities>;
  isAdmin: boolean;
  session: Session;
  billingHref: string;
}) {
  const t = useTranslations("settings.organization");

  // ── Org ID copy ─────────────────────────────────────────────────────────────
  const [orgIdCopied, setOrgIdCopied] = useState(false);

  function handleCopyOrgId(): void {
    const orgId = session?.organizationId;
    if (!orgId) return;
    void navigator.clipboard.writeText(orgId).then(() => {
      setOrgIdCopied(true);
      setTimeout(() => setOrgIdCopied(false), 2000);
    });
  }

  // ── Organization profile form ───────────────────────────────────────────────
  const [profileSaveState, setProfileSaveState] = useState<SaveState>(null);
  const profileLastSavedRef = useRef<OrgProfileFormValues | null>(null);

  const defaultProfileValues: OrgProfileFormValues = {
    name: session?.organizationName ?? "",
    slug: "",
    primaryDomain: "",
    domainAllowlist: "",
    supportEmail: "",
    description: "",
  };

  const profileForm = useForm<OrgProfileFormValues>({
    resolver: zodResolver(orgProfileSchema),
    defaultValues: defaultProfileValues,
    mode: "onSubmit",
  });

  const watchedOrgName = useWatch({
    control: profileForm.control,
    name: "name",
    defaultValue: defaultProfileValues.name,
  });

  const profileQuery = useQuery({
    queryKey: queryKeys.organization.profile,
    queryFn: getOrganizationProfile,
    enabled: capabilities.profileEnabled,
    retry: false,
  });

  useEffect(() => {
    if (!profileQuery.data) return;
    const values = profileToForm(profileQuery.data);
    profileLastSavedRef.current = values;
    profileForm.reset(values);
  }, [profileForm, profileQuery.data]);

  const profileSaveMutation = useMutation({
    mutationFn: (values: OrgProfileFormValues) =>
      updateOrganizationProfile({
        name: values.name,
        slug: values.slug,
        primary_domain: values.primaryDomain || null,
        domain_allowlist: toList(values.domainAllowlist),
        support_email: values.supportEmail || null,
        description: values.description || null,
      }),
    onSuccess: (updated) => {
      const values = profileToForm(updated);
      profileLastSavedRef.current = values;
      profileForm.reset(values);
      setProfileSaveState({
        tone: "success",
        message: t("profile.saved"),
      });
    },
    onError: (error) => {
      setProfileSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveProfile(): Promise<void> {
    setProfileSaveState(null);
    const valid = await profileForm.trigger();
    if (!valid) return;
    await profileSaveMutation.mutateAsync(profileForm.getValues());
  }

  function handleDiscardProfile(): void {
    const last = profileLastSavedRef.current ?? defaultProfileValues;
    profileForm.reset(last);
    setProfileSaveState(null);
  }

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Organization section"
    >
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Building2 size={20} className="text-[#3525cd]" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-[#1b1b24]">
            {t("profile.title")}
          </h2>
        </div>
        {!capabilities.profileEnabled && (
          <DeploymentControlledBadge label={t("deploymentControlled")} />
        )}
      </div>

      {/* Always-visible: org ID + basic session info */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
            {t("profile.orgId")}
          </p>
          {session?.organizationId ? (
            <div className="flex items-center justify-between gap-2 rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2">
              <span className="max-w-[180px] truncate font-mono text-xs text-[#464555]">
                {session.organizationId}
              </span>
              <button
                type="button"
                onClick={handleCopyOrgId}
                aria-label={t("profile.copyOrgIdAriaLabel")}
                className="shrink-0 rounded-lg border border-[#c7c4d8] px-2 py-0.5 text-xs font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
              >
                {orgIdCopied ? (
                  <CopyCheck size={12} aria-hidden="true" />
                ) : (
                  <Copy size={12} aria-hidden="true" />
                )}
                <span className="sr-only">
                  {orgIdCopied ? t("profile.copied") : t("profile.copy")}
                </span>
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2 text-sm text-[#464555]">
              {t("profile.notAssigned")}
            </div>
          )}
        </div>

        <ReadOnlyField
          label={t("profile.name")}
          value={session?.organizationName}
          notAvailableLabel={t("profile.notAssigned")}
        />
      </div>

      {/* Profile API content */}
      {!capabilities.profileEnabled ||
      isOrganizationEndpointUnavailableError(profileQuery.error) ? (
        <p className="text-sm text-[#777587]">{t("profile.unavailable")}</p>
      ) : profileQuery.isLoading ? (
        <LoadingState compact title={t("profile.loading")} />
      ) : profileQuery.isError ? (
        <ErrorState
          compact
          error={profileQuery.error}
          description={getApiErrorMessage(profileQuery.error)}
          onRetry={() => {
            void profileQuery.refetch();
          }}
        />
      ) : isAdmin ? (
        /* Editable profile form for owner/admin */
        <div className="space-y-4">
          {/* Avatar preview */}
          <div className="flex items-center gap-4 rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
            {(() => {
              const colors = orgAvatarColor(watchedOrgName);
              const initials = orgInitials(watchedOrgName || "W");
              return (
                <span
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-base font-bold"
                  style={{ backgroundColor: colors.bg, color: colors.text }}
                  aria-hidden
                >
                  {initials}
                </span>
              );
            })()}
            <div>
              <p className="text-sm font-semibold text-[#2a2640]">
                {watchedOrgName.trim() || t("profile.workspaceName")}
              </p>
              <p className="text-xs text-[#7a7693]">
                {t("profile.avatarHint")}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <FieldLabel htmlFor="org-name">{t("profile.name")}</FieldLabel>
              <input
                id="org-name"
                {...profileForm.register("name")}
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              {profileForm.formState.errors.name?.message && (
                <p role="alert" className="text-xs text-rose-700">
                  {profileForm.formState.errors.name.message}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="org-slug">{t("profile.slug")}</FieldLabel>
              <input
                id="org-slug"
                {...profileForm.register("slug")}
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 font-mono text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                placeholder="my-org"
              />
              {profileForm.formState.errors.slug?.message && (
                <p role="alert" className="text-xs text-rose-700">
                  {profileForm.formState.errors.slug.message}
                </p>
              )}
              <p className="text-xs text-[#777587]">{t("profile.slugHint")}</p>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="org-primary-domain">
                {t("profile.primaryDomain")}
              </FieldLabel>
              <input
                id="org-primary-domain"
                {...profileForm.register("primaryDomain")}
                placeholder="example.com"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              {profileForm.formState.errors.primaryDomain?.message && (
                <p role="alert" className="text-xs text-rose-700">
                  {profileForm.formState.errors.primaryDomain.message}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="org-support-email">
                {t("profile.supportEmail")}
              </FieldLabel>
              <input
                id="org-support-email"
                type="email"
                {...profileForm.register("supportEmail")}
                placeholder="support@example.com"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              {profileForm.formState.errors.supportEmail?.message && (
                <p role="alert" className="text-xs text-rose-700">
                  {profileForm.formState.errors.supportEmail.message}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-1">
            <FieldLabel htmlFor="org-domain-allowlist">
              {t("profile.domainAllowlist")}
            </FieldLabel>
            <input
              id="org-domain-allowlist"
              {...profileForm.register("domainAllowlist")}
              placeholder="example.com, partner.org"
              className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
            <p className="text-xs text-[#777587]">
              {t("profile.domainAllowlistHint", {
                example: "acme.com, partner.org",
              })}
            </p>
          </div>

          <div className="space-y-1">
            <FieldLabel htmlFor="org-description">
              {t("profile.description")}
            </FieldLabel>
            <textarea
              id="org-description"
              {...profileForm.register("description")}
              rows={3}
              className="w-full resize-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
          </div>

          {/* Profile API metadata */}
          {profileQuery.data && (
            <div className="grid grid-cols-1 gap-3 rounded-xl border border-[#e4e1ee] bg-[#f5f2ff]/50 p-4 sm:grid-cols-2">
              <div>
                <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                  {t("profile.created")}
                </p>
                <p className="mt-0.5 text-sm text-[#2f2a46]">
                  {formatDate(profileQuery.data.created_at)}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                  {t("profile.currentPlan")}
                </p>
                <p className="mt-0.5 text-sm text-[#2f2a46]">
                  {profileQuery.data.plan ?? t("notAvailable")}{" "}
                  <Link
                    href={billingHref}
                    className="text-xs text-[#3525cd] underline-offset-2 hover:underline"
                  >
                    {t("profile.viewBilling")}
                  </Link>
                </p>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-3">
            <SaveFeedback state={profileSaveState} />
            <button
              type="button"
              onClick={handleDiscardProfile}
              disabled={profileSaveMutation.isPending}
              className="rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t("discard")}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleSaveProfile();
              }}
              disabled={profileSaveMutation.isPending}
              aria-label={t("profile.saveAriaLabel")}
              className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {profileSaveMutation.isPending ? t("saving") : t("profile.save")}
            </button>
          </div>
        </div>
      ) : (
        /* Read-only profile for member/viewer */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ReadOnlyField
            label={t("profile.slug")}
            value={profileQuery.data?.slug}
            notAvailableLabel={t("notAvailable")}
          />
          <ReadOnlyField
            label={t("profile.primaryDomain")}
            value={profileQuery.data?.primary_domain}
            notAvailableLabel={t("notAvailable")}
          />
          <ReadOnlyField
            label={t("profile.supportEmail")}
            value={profileQuery.data?.support_email}
            notAvailableLabel={t("notAvailable")}
          />
          <ReadOnlyField
            label={t("profile.description")}
            value={profileQuery.data?.description}
            notAvailableLabel={t("notAvailable")}
          />
          <ReadOnlyField
            label={t("profile.created")}
            value={formatDate(profileQuery.data?.created_at ?? null)}
            notAvailableLabel={t("notAvailable")}
          />
          <ReadOnlyField
            label={t("profile.currentPlan")}
            value={profileQuery.data?.plan}
            notAvailableLabel={t("notAvailable")}
          />
        </div>
      )}
    </section>
  );
}
