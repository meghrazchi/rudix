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

function safeErrorMessage(error: unknown): string {
  if (error instanceof ContactSubmissionError) {
    return error.safeMessage;
  }

  return "Unable to submit your request right now. Please try again.";
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
      setSubmissionSuccess(result.successMessage);

      if (result.redirectTo && typeof window !== "undefined") {
        window.location.assign(result.redirectTo);
      }

      form.reset(defaultValues());
    } catch (error) {
      setSubmissionError(safeErrorMessage(error));
    }
  }

  return (
    <div className="rounded-xl border border-[#d7dce8] bg-white p-7 shadow-sm md:p-10">
      <h2 className="text-2xl font-black text-[#141826]">{t("title")}</h2>
      <p className="mt-2 text-sm leading-7 text-[#5e657b]">
        {t("messagePlaceholder")}
      </p>

      {isUnavailable ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Contact submission is not configured right now. You can still reach
          the team through alternate contact paths.
        </div>
      ) : null}

      {submissionSuccess ? (
        <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {submissionSuccess}
        </div>
      ) : null}

      {submissionError ? (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <p>{submissionError}</p>
          <PublicActionLink
            href={retryHref}
            className="mt-2 inline-block font-semibold underline decoration-rose-300"
          >
            Retry with alternate contact path
          </PublicActionLink>
        </div>
      ) : null}

      <form
        className="mt-6 space-y-5"
        onSubmit={form.handleSubmit(onSubmit)}
        noValidate
      >
        <div className="hidden" aria-hidden="true">
          <label htmlFor="website">Website</label>
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
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              {t("firstName")} {t("lastName")}
            </span>
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              {...form.register("fullName")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            />
            {form.formState.errors.fullName?.message ? (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.fullName.message}
              </p>
            ) : null}
          </label>

          <label htmlFor="workEmail" className="block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              {t("email")}
            </span>
            <input
              id="workEmail"
              type="email"
              autoComplete="email"
              {...form.register("workEmail")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            />
            {form.formState.errors.workEmail?.message ? (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.workEmail.message}
              </p>
            ) : null}
          </label>

          <label htmlFor="company" className="block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              {t("company")}
            </span>
            <input
              id="company"
              type="text"
              autoComplete="organization"
              {...form.register("company")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            />
            {form.formState.errors.company?.message ? (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.company.message}
              </p>
            ) : null}
          </label>

          <label htmlFor="teamSize" className="block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              Team size
            </span>
            <select
              id="teamSize"
              {...form.register("teamSize")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            >
              <option value="">Select team size</option>
              {CONTACT_TEAM_SIZE_OPTIONS.map((teamSize) => (
                <option key={teamSize} value={teamSize}>
                  {teamSize}
                </option>
              ))}
            </select>
            {form.formState.errors.teamSize?.message ? (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.teamSize.message}
              </p>
            ) : null}
          </label>

          <label htmlFor="roleTitle" className="block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              {t("role")}
            </span>
            <select
              id="roleTitle"
              {...form.register("roleTitle")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            >
              <option value="">{t("rolePlaceholder")}</option>
              {CONTACT_ROLE_OPTIONS.map((roleOption) => (
                <option key={roleOption.value} value={roleOption.label}>
                  {roleOption.label}
                </option>
              ))}
            </select>
            {form.formState.errors.roleTitle?.message ? (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.roleTitle.message}
              </p>
            ) : null}
          </label>

          <label htmlFor="useCase" className="block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              {t("useCase")}
            </span>
            <select
              id="useCase"
              {...form.register("useCase")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            >
              <option value="">{t("useCasePlaceholder")}</option>
              {CONTACT_USE_CASE_OPTIONS.map((useCaseOption) => (
                <option key={useCaseOption.value} value={useCaseOption.label}>
                  {useCaseOption.label}
                </option>
              ))}
            </select>
            {form.formState.errors.useCase?.message ? (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.useCase.message}
              </p>
            ) : null}
          </label>
        </div>

        <label htmlFor="message" className="block">
          <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
            {t("message")}
          </span>
          <textarea
            id="message"
            rows={4}
            {...form.register("message")}
            className="w-full rounded-lg border border-[#d2d7e4] px-3 py-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            placeholder={t("messagePlaceholder")}
          />
          {form.formState.errors.message?.message ? (
            <p role="alert" className="mt-1 text-xs text-rose-700">
              {form.formState.errors.message.message}
            </p>
          ) : null}
        </label>

        {submissionConfig.captchaProvider ? (
          <label htmlFor="captchaToken" className="block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#696f84] uppercase">
              CAPTCHA token ({submissionConfig.captchaProvider})
            </span>
            <input
              id="captchaToken"
              type="text"
              {...form.register("captchaToken")}
              className="h-11 w-full rounded-lg border border-[#d2d7e4] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
              placeholder="Optional placeholder for provider integration"
            />
            <p className="mt-1 text-xs text-[#697189]">
              Configure client-side CAPTCHA provider integration to populate
              this field in production deployments.
            </p>
          </label>
        ) : null}

        <label className="flex items-start gap-3" htmlFor="consentAccepted">
          <input
            id="consentAccepted"
            type="checkbox"
            {...form.register("consentAccepted")}
            className="mt-1 h-4 w-4 rounded border-[#bfc5d6] text-[#3525cd] focus:ring-[#3525cd]/30"
          />
          <span className="text-sm text-[#4f5670]">
            I agree that Rudix may use this information to contact me about a
            demo or solution discussion.
          </span>
        </label>
        {form.formState.errors.consentAccepted?.message ? (
          <p role="alert" className="-mt-2 text-xs text-rose-700">
            {form.formState.errors.consentAccepted.message}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={form.formState.isSubmitting || isUnavailable}
          className="inline-flex h-11 w-full items-center justify-center rounded-lg bg-[#3525cd] px-4 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {form.formState.isSubmitting ? t("submitting") : t("submit")}
        </button>
      </form>

      {schedulerHref ? (
        <div className="mt-5 border-t border-[#e4e8f2] pt-5">
          <p className="text-sm text-[#5e657b]">{t("schedulerLabel")}</p>
          <PublicActionLink
            href={schedulerHref}
            className="mt-1 inline-block text-sm font-semibold text-[#3128ad] underline decoration-[#b8bde9]"
          >
            {t("schedulerCta")}
          </PublicActionLink>
        </div>
      ) : null}

      <div className="mt-4 border-t border-[#e4e8f2] pt-4">
        <p className="text-sm text-[#5e657b]">{t("fallbackEmailLabel")}</p>
        <PublicActionLink
          href={supportHref}
          className="mt-1 inline-block text-sm font-semibold text-[#3128ad] underline decoration-[#b8bde9]"
        >
          {t("fallbackCta")}
        </PublicActionLink>
      </div>
    </div>
  );
}
