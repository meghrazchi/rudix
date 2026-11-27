"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  CONTACT_ROLE_OPTIONS,
  CONTACT_USE_CASE_OPTIONS,
} from "@/components/public/pages/contact/contactData";
import {
  CONTACT_TEAM_SIZE_OPTIONS,
  ContactSubmissionError,
  contactFormSchema,
  type ContactFormInputValues,
  submitContactForm,
  type ContactSubmissionConfig,
} from "@/lib/public-site/contact";

type ContactDemoFormCardProps = {
  submissionConfig: ContactSubmissionConfig;
  supportHref: string;
  schedulerHref: string | null;
};

function safeErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ContactSubmissionError) {
    return error.safeMessage;
  }

  return fallback;
}

function defaultValues(): ContactFormInputValues {
  return {
    fullName: "",
    workEmail: "",
    company: "",
    roleTitle: "",
    useCase: "",
    teamSize: "",
    message: "",
    consentAccepted: false,
    honeypot: "",
    captchaToken: "",
  };
}

export function ContactDemoFormCard({
  submissionConfig,
  supportHref,
  schedulerHref,
}: ContactDemoFormCardProps) {
  const t = useTranslations("public.contact.form");
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [submissionSuccess, setSubmissionSuccess] = useState<string | null>(
    null,
  );

  const form = useForm<ContactFormInputValues>({
    resolver: zodResolver(contactFormSchema),
    defaultValues: defaultValues(),
    mode: "onSubmit",
  });

  const isUnavailable = submissionConfig.mode === "unavailable";

  const retryHref = useMemo(() => {
    return schedulerHref ?? supportHref;
  }, [schedulerHref, supportHref]);

  async function onSubmit(values: ContactFormInputValues) {
    setSubmissionError(null);
    setSubmissionSuccess(null);

    try {
      const result = await submitContactForm(values, submissionConfig);
      setSubmissionSuccess(t(`successChannels.${result.channel}`));

      if (result.redirectTo && typeof window !== "undefined") {
        window.location.assign(result.redirectTo);
      }

      form.reset(defaultValues());
    } catch (error) {
      setSubmissionError(
        error instanceof ContactSubmissionError
          ? t(`errors.${error.kind}`)
          : safeErrorMessage(error, t("errors.unknown")),
      );
    }
  }

  return (
    <div className="border-site-border bg-site-surface rounded-2xl border p-7 md:p-10">
      <h2 className="text-site-ink text-2xl font-semibold tracking-tight">
        {t("title")}
      </h2>
      <p className="text-site-ink-muted mt-2 text-sm leading-7">
        {t("messagePlaceholder")}
      </p>

      {isUnavailable ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
          {t("unconfiguredNotice")}
        </div>
      ) : null}

      {submissionSuccess ? (
        <div className="border-site-success/30 bg-site-success-soft text-site-success mt-4 rounded-lg border px-4 py-3 text-sm">
          {submissionSuccess}
        </div>
      ) : null}

      {submissionError ? (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200">
          <p>{submissionError}</p>
          <PublicActionLink
            href={retryHref}
            className="mt-2 inline-block font-semibold underline decoration-rose-300"
          >
            {t("retryLink")}
          </PublicActionLink>
        </div>
      ) : null}

      <form
        className="mt-6 space-y-5"
        onSubmit={form.handleSubmit(onSubmit)}
        noValidate
      >
        <div className="hidden" aria-hidden="true">
          <label htmlFor="website">{t("website")}</label>
          <input
            id="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            {...form.register("honeypot")}
          />
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          <label htmlFor="fullName" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("firstName")} {t("lastName")}
            </span>
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              {...form.register("fullName")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
            />
            {form.formState.errors.fullName?.message ? (
              <p
                role="alert"
                className="mt-1 text-xs text-rose-700 dark:text-rose-300"
              >
                {t("validation.fullName")}
              </p>
            ) : null}
          </label>

          <label htmlFor="workEmail" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("email")}
            </span>
            <input
              id="workEmail"
              type="email"
              autoComplete="email"
              {...form.register("workEmail")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
            />
            {form.formState.errors.workEmail?.message ? (
              <p
                role="alert"
                className="mt-1 text-xs text-rose-700 dark:text-rose-300"
              >
                {t("validation.workEmail")}
              </p>
            ) : null}
          </label>

          <label htmlFor="company" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("company")}
            </span>
            <input
              id="company"
              type="text"
              autoComplete="organization"
              {...form.register("company")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
            />
            {form.formState.errors.company?.message ? (
              <p
                role="alert"
                className="mt-1 text-xs text-rose-700 dark:text-rose-300"
              >
                {t("validation.company")}
              </p>
            ) : null}
          </label>

          <label htmlFor="teamSize" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("teamSize")}
            </span>
            <select
              id="teamSize"
              {...form.register("teamSize")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
            >
              <option value="">{t("teamSizePlaceholder")}</option>
              {CONTACT_TEAM_SIZE_OPTIONS.map((teamSize) => (
                <option key={teamSize} value={teamSize}>
                  {teamSize}
                </option>
              ))}
            </select>
            {form.formState.errors.teamSize?.message ? (
              <p
                role="alert"
                className="mt-1 text-xs text-rose-700 dark:text-rose-300"
              >
                {t("validation.teamSize")}
              </p>
            ) : null}
          </label>

          <label htmlFor="roleTitle" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("role")}
            </span>
            <select
              id="roleTitle"
              {...form.register("roleTitle")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
            >
              <option value="">{t("rolePlaceholder")}</option>
              {CONTACT_ROLE_OPTIONS.map((roleOption) => (
                <option key={roleOption.value} value={roleOption.label}>
                  {t(`roleOptions.${roleOption.value}`)}
                </option>
              ))}
            </select>
            {form.formState.errors.roleTitle?.message ? (
              <p
                role="alert"
                className="mt-1 text-xs text-rose-700 dark:text-rose-300"
              >
                {t("validation.roleTitle")}
              </p>
            ) : null}
          </label>

          <label htmlFor="useCase" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("useCase")}
            </span>
            <select
              id="useCase"
              {...form.register("useCase")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
            >
              <option value="">{t("useCasePlaceholder")}</option>
              {CONTACT_USE_CASE_OPTIONS.map((useCaseOption) => (
                <option key={useCaseOption.value} value={useCaseOption.label}>
                  {t(`useCaseOptions.${useCaseOption.value}`)}
                </option>
              ))}
            </select>
            {form.formState.errors.useCase?.message ? (
              <p
                role="alert"
                className="mt-1 text-xs text-rose-700 dark:text-rose-300"
              >
                {t("validation.useCase")}
              </p>
            ) : null}
          </label>
        </div>

        <label htmlFor="message" className="block">
          <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
            {t("message")}
          </span>
          <textarea
            id="message"
            rows={4}
            {...form.register("message")}
            className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 w-full rounded-xl border px-3.5 py-3 text-sm transition outline-none focus:ring-2"
            placeholder={t("messagePlaceholder")}
          />
          {form.formState.errors.message?.message ? (
            <p
              role="alert"
              className="mt-1 text-xs text-rose-700 dark:text-rose-300"
            >
              {t("validation.message")}
            </p>
          ) : null}
        </label>

        {submissionConfig.captchaProvider ? (
          <label htmlFor="captchaToken" className="block">
            <span className="text-site-ink-muted mb-1.5 block text-xs font-medium">
              {t("captchaToken", {
                provider: submissionConfig.captchaProvider,
              })}
            </span>
            <input
              id="captchaToken"
              type="text"
              {...form.register("captchaToken")}
              className="border-site-border bg-site-canvas text-site-ink focus:border-site-accent focus:ring-site-accent/20 h-11 w-full rounded-xl border px-3.5 text-sm transition outline-none focus:ring-2"
              placeholder={t("captchaPlaceholder")}
            />
            <p className="text-site-ink-subtle mt-1 text-xs">
              {t("captchaDescription")}
            </p>
          </label>
        ) : null}

        <label className="flex items-start gap-3" htmlFor="consentAccepted">
          <input
            id="consentAccepted"
            type="checkbox"
            {...form.register("consentAccepted")}
            className="border-site-border mt-1 h-4 w-4 rounded accent-[var(--site-accent)]"
          />
          <span className="text-site-ink-muted text-sm">{t("consent")}</span>
        </label>
        {form.formState.errors.consentAccepted?.message ? (
          <p
            role="alert"
            className="-mt-2 text-xs text-rose-700 dark:text-rose-300"
          >
            {t("validation.consent")}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={form.formState.isSubmitting || isUnavailable}
          className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover inline-flex h-11 w-full items-center justify-center rounded-full px-4 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
        >
          {form.formState.isSubmitting ? t("submitting") : t("submit")}
        </button>
      </form>

      {schedulerHref ? (
        <div className="border-site-border mt-5 border-t pt-5">
          <p className="text-site-ink-muted text-sm">{t("schedulerLabel")}</p>
          <PublicActionLink
            href={schedulerHref}
            className="text-site-accent-ink decoration-site-accent/40 mt-1 inline-block text-sm font-semibold underline"
          >
            {t("schedulerCta")}
          </PublicActionLink>
        </div>
      ) : null}

      <div className="border-site-border mt-4 border-t pt-4">
        <p className="text-site-ink-muted text-sm">{t("fallbackEmailLabel")}</p>
        <PublicActionLink
          href={supportHref}
          className="text-site-accent-ink decoration-site-accent/40 mt-1 inline-block text-sm font-semibold underline"
        >
          {t("fallbackCta")}
        </PublicActionLink>
      </div>
    </div>
  );
}
