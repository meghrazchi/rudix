"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  createSignupFormSchema,
  getSignupProviderLabel,
  getSignupSsoStartHref,
  startSignupSession,
  type SignupFlowError,
  type SignupFormValues,
} from "@/lib/auth-signup";
import { resolveAuthenticatedNavigationTarget } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";
import { trackActivationEvent } from "@/lib/analytics";
import { useAuthSession } from "@/lib/use-auth-session";

function safeErrorMessage(
  error: unknown,
  t: ReturnType<typeof useTranslations>,
): string {
  if (error instanceof Error && "kind" in error) {
    const kind = (error as SignupFlowError).kind;
    const errorKeys: Record<SignupFlowError["kind"], string> = {
      duplicate_email: "signupErrorDuplicateEmail",
      weak_password: "signupErrorWeakPassword",
      invite_only: "signupErrorInviteOnly",
      provider_error: "signupErrorProvider",
      network_failure: "signupErrorNetwork",
      not_configured: "signupErrorNotConfigured",
      unknown: "signupFailed",
    };
    return t(errorKeys[kind]);
  }

  if (typeof error === "object" && error !== null && "safeMessage" in error) {
    const candidate = error as Partial<SignupFlowError> & {
      safeMessage?: unknown;
    };
    if (
      typeof candidate.safeMessage === "string" &&
      candidate.safeMessage.trim()
    ) {
      return candidate.safeMessage;
    }
  }

  return t("signupFailed");
}

function resolvePostSignupTarget(
  nextPath: string,
  nextStep: "onboarding" | "dashboard",
  session: AuthenticatedSession,
): string {
  if (nextStep === "onboarding") {
    return "/organization-onboarding";
  }

  if (
    !nextPath ||
    nextPath === "/login" ||
    nextPath === "/signup" ||
    nextPath === "/organization-onboarding"
  ) {
    return resolveAuthenticatedNavigationTarget("/dashboard", session);
  }

  return resolveAuthenticatedNavigationTarget(nextPath, session);
}

export default function SignupPage() {
  return (
    <Suspense fallback={<SignupPageFallback />}>
      <SignupPageContent />
    </Suspense>
  );
}

function SignupPageFallback() {
  const t = useTranslations("auth");
  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="border-site-border bg-site-surface w-full max-w-2xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <p className="text-site-ink-muted text-sm">{t("loadingSignUp")}</p>
      </main>
    </div>
  );
}

function SignupPageContent() {
  const t = useTranslations("auth");
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";
  const { state, setAuthenticatedSession } = useAuthSession();

  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const localizedSignupFormSchema = useMemo(
    () =>
      createSignupFormSchema({
        fullNameRequired: t("fullNameRequired"),
        fullNameMinLength: t("fullNameMinLength"),
        emailRequired: t("emailRequired"),
        emailInvalid: t("emailInvalid"),
        passwordRequired: t("passwordRequired"),
        passwordMinLength: t("passwordMinLength"),
        workspaceNameMinLength: t("workspaceNameMinLength"),
        inviteCodeRequired: t("inviteCodeRequired"),
        termsRequired: t("termsRequired"),
      }),
    [t],
  );

  const form = useForm<SignupFormValues>({
    resolver: zodResolver(localizedSignupFormSchema),
    defaultValues: {
      fullName: "",
      email: "",
      password: "",
      workspaceMode: "create",
      workspaceName: "",
      inviteCode: "",
      acceptTerms: false,
    },
    mode: "onSubmit",
  });

  const workspaceMode = useWatch({
    control: form.control,
    name: "workspaceMode",
  });
  const ssoStartHref = getSignupSsoStartHref(nextPath);
  const providerLabel = getSignupProviderLabel();

  useEffect(() => {
    if (state.status === "authenticated" && state.session) {
      router.replace(
        resolveAuthenticatedNavigationTarget(nextPath, state.session),
      );
    }
  }, [nextPath, router, state]);

  async function onSubmit(values: SignupFormValues) {
    setSubmissionError(null);

    try {
      const result = await startSignupSession(values);
      void trackActivationEvent("activation.signup_completed", {
        surface: "public",
        route: "/signup",
        pageKey: "signup",
        featureArea: "public",
        source: values.workspaceMode,
      });
      setAuthenticatedSession(result.session);
      router.replace(
        resolvePostSignupTarget(nextPath, result.nextStep, result.session),
      );
    } catch (error) {
      setSubmissionError(safeErrorMessage(error, t));
    }
  }

  function handleStartProviderSignup() {
    if (!ssoStartHref) {
      setSubmissionError(t("signupSsoNotConfigured"));
      return;
    }

    if (
      ssoStartHref.startsWith("http://") ||
      ssoStartHref.startsWith("https://")
    ) {
      window.location.assign(ssoStartHref);
      return;
    }

    router.push(ssoStartHref);
  }

  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6 py-8"
    >
      <main className="border-site-border bg-site-surface w-full max-w-2xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <div className="mb-2 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt={t("rudixLogo")}
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-site-ink-muted text-xs font-bold tracking-[0.18em] uppercase">
            {t("signInLabel")}
          </p>
        </div>
        <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
          {t("signUpTitle")}
        </h1>
        <p className="text-site-ink-muted mb-6 text-sm">
          {t("signUpDescription")}
        </p>

        <form
          className="space-y-4"
          onSubmit={form.handleSubmit(onSubmit)}
          noValidate
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block" htmlFor="fullName">
              <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                {t("fullName")}
              </span>
              <input
                id="fullName"
                type="text"
                autoComplete="name"
                {...form.register("fullName")}
                className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
              />
            </label>

            <label className="block" htmlFor="email">
              <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                {t("email")}
              </span>
              <input
                id="email"
                type="email"
                autoComplete="email"
                {...form.register("email")}
                className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
              />
            </label>
          </div>

          {form.formState.errors.fullName?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.fullName.message}
            </p>
          ) : null}
          {form.formState.errors.email?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.email.message}
            </p>
          ) : null}

          <label className="block" htmlFor="password">
            <span className="text-site-ink-muted mb-1 block text-xs font-medium">
              {t("password")}
            </span>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              {...form.register("password")}
              className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
            />
          </label>
          {form.formState.errors.password?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.password.message}
            </p>
          ) : null}

          <fieldset className="border-site-border bg-site-surface rounded-lg border p-4">
            <legend className="text-site-ink-muted px-1 text-xs font-medium">
              {t("workspace")}
            </legend>
            <div className="mt-2 space-y-2">
              <label className="text-site-ink flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  value="create"
                  {...form.register("workspaceMode")}
                />
                {t("createWorkspace")}
              </label>
              <label className="text-site-ink flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  value="join"
                  {...form.register("workspaceMode")}
                />
                {t("joinWorkspace")}
              </label>
            </div>

            {workspaceMode === "create" ? (
              <label className="mt-3 block" htmlFor="workspaceName">
                <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                  {t("workspaceName")}
                </span>
                <input
                  id="workspaceName"
                  type="text"
                  {...form.register("workspaceName")}
                  className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
                />
              </label>
            ) : (
              <label className="mt-3 block" htmlFor="inviteCode">
                <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                  {t("workspaceInviteCode")}
                </span>
                <input
                  id="inviteCode"
                  type="text"
                  {...form.register("inviteCode")}
                  className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
                />
              </label>
            )}
          </fieldset>

          {form.formState.errors.workspaceName?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.workspaceName.message}
            </p>
          ) : null}
          {form.formState.errors.inviteCode?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.inviteCode.message}
            </p>
          ) : null}

          <label className="border-site-border bg-site-surface text-site-ink flex items-start gap-2 rounded-lg border p-3 text-sm">
            <input
              type="checkbox"
              {...form.register("acceptTerms")}
              className="mt-0.5"
            />
            <span>{t("acceptTerms")}</span>
          </label>
          {form.formState.errors.acceptTerms?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.acceptTerms.message}
            </p>
          ) : null}

          {submissionError ? (
            <p
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
            >
              {submissionError}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={form.formState.isSubmitting || state.status === "loading"}
            className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover h-10 w-full rounded-full px-5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
          >
            {form.formState.isSubmitting
              ? t("creatingAccount")
              : t("createAccount")}
          </button>
        </form>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <Link
            href="/login"
            className="text-site-ink-muted decoration-site-ink-subtle text-sm font-semibold underline"
          >
            {t("alreadyHaveAccount")} {t("signIn")}
          </Link>
          <Link
            href="/"
            className="text-site-ink-muted decoration-site-ink-subtle text-sm font-semibold underline"
          >
            {t("backToHome")}
          </Link>
        </div>

        {ssoStartHref ? (
          <div className="border-site-border mt-5 border-t pt-5">
            <button
              type="button"
              onClick={handleStartProviderSignup}
              className="border-site-border bg-site-surface text-site-accent-ink hover:bg-site-canvas h-10 w-full rounded-lg border px-5 text-sm font-semibold transition"
            >
              {t("continueWith", { provider: providerLabel })}
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}
