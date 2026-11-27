"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Suspense, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  discoverSSOForEmail,
  getForgotPasswordHref,
  getLoginProviderLabel,
  getSsoStartHref,
  loginFormSchema,
  startLoginSession,
  type LoginFormValues,
  type LoginFlowError,
  type SSODiscoveryState,
} from "@/lib/auth-login";
import { getAuthBoundaryMessageKey } from "@/lib/auth-session";
import { resolveAuthenticatedNavigationTarget } from "@/lib/app-routes";
import { useAuthSession } from "@/lib/use-auth-session";

function safeErrorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "safeMessage" in error) {
    const candidate = error as Partial<LoginFlowError> & {
      safeMessage?: unknown;
    };
    if (
      typeof candidate.safeMessage === "string" &&
      candidate.safeMessage.trim()
    ) {
      return candidate.safeMessage;
    }
  }
  return fallback;
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginPageFallback />}>
      <LoginPageContent />
    </Suspense>
  );
}

function LoginPageFallback() {
  const t = useTranslations("auth");
  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="border-site-border bg-site-surface w-full max-w-xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <p className="text-site-ink-muted text-sm">{t("loadingSignIn")}</p>
      </main>
    </div>
  );
}

function LoginPageContent() {
  const t = useTranslations("auth");
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";
  const authReason = searchParams.get("reason");
  const {
    state,
    setAuthenticatedSession,
    boundaryMessageKey,
    clearBoundaryEvent,
  } = useAuthSession();

  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [forgotPlaceholderMessage, setForgotPlaceholderMessage] = useState<
    string | null
  >(null);
  const [ssoDiscovery, setSsoDiscovery] = useState<SSODiscoveryState>({
    status: "idle",
  });

  // No defaultValues: react-hook-form then reads each input's current value
  // when it registers, so text typed into the server-rendered form before
  // hydration is kept (a protected-route redirect to /login is a full page
  // load since the public and app groups have separate root layouts, R07-01).
  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginFormSchema),
    mode: "onSubmit",
  });

  const authBoundaryKey =
    getAuthBoundaryMessageKey(authReason) ?? boundaryMessageKey;
  const authNoticeMessage = authBoundaryKey ? t(authBoundaryKey) : null;
  const ssoStartHref = getSsoStartHref(nextPath);
  const hasSsoEntry = Boolean(ssoStartHref);
  const forgotPasswordHref = getForgotPasswordHref();
  const providerLabel = getLoginProviderLabel();

  useEffect(() => {
    if (state.status === "authenticated" && state.session) {
      router.replace(
        resolveAuthenticatedNavigationTarget(nextPath, state.session),
      );
    }
  }, [nextPath, router, state]);

  useEffect(() => {
    if (authReason || boundaryMessageKey) {
      clearBoundaryEvent();
    }
  }, [authReason, boundaryMessageKey, clearBoundaryEvent]);

  async function handleEmailBlur() {
    const email = form.getValues("email");
    if (!email.trim() || !email.includes("@")) return;
    setSsoDiscovery({ status: "loading" });
    const result = await discoverSSOForEmail(email);
    setSsoDiscovery(result);
  }

  async function onSubmit(values: LoginFormValues) {
    setSubmissionError(null);
    setForgotPlaceholderMessage(null);

    try {
      const session = await startLoginSession(values);
      setAuthenticatedSession(session);
      router.replace(resolveAuthenticatedNavigationTarget(nextPath, session));
    } catch (error) {
      setSubmissionError(safeErrorMessage(error, t("signInFailed")));
    }
  }

  function handleStartSso() {
    if (!ssoStartHref) {
      setSubmissionError(t("ssoNotConfigured"));
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

  function handleForgotPasswordPlaceholder() {
    setForgotPlaceholderMessage(t("passwordResetNotConfigured"));
  }

  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="border-site-border bg-site-surface w-full max-w-xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <div className="mb-2 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-site-ink-muted text-xs font-bold tracking-[0.18em] uppercase">
            {t("signInLabel")}
          </p>
        </div>
        <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
          {t("signIn")}
        </h1>
        <p className="text-site-ink-muted mb-6 text-sm">
          {t("signInDescription")}
        </p>

        {authNoticeMessage ? (
          <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
            {authNoticeMessage}
          </p>
        ) : null}

        <form
          className="space-y-4"
          onSubmit={form.handleSubmit(onSubmit)}
          noValidate
        >
          <label className="block" htmlFor="email">
            <span className="text-site-ink-muted mb-1 block text-xs font-medium">
              {t("email")}
            </span>
            <input
              id="email"
              type="email"
              autoComplete="email"
              {...form.register("email")}
              onBlur={handleEmailBlur}
              className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
            />
          </label>
          {form.formState.errors.email?.message ? (
            <p
              role="alert"
              className="text-xs text-rose-700 dark:text-rose-300"
            >
              {form.formState.errors.email.message}
            </p>
          ) : null}

          {ssoDiscovery.status === "found" ? (
            <div className="border-site-accent/25 bg-site-accent-soft text-site-accent-ink rounded-lg border px-3 py-2.5 text-sm">
              <p className="font-semibold">
                {t("ssoAvailableFor", { domain: ssoDiscovery.domain })}
              </p>
              <p className="text-site-accent-ink mt-0.5 text-xs">
                {t("ssoDescription")}
              </p>
              <button
                type="button"
                onClick={() => window.location.assign(ssoDiscovery.redirectUrl)}
                className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover mt-2 rounded-full px-3 py-1.5 text-xs font-semibold transition"
              >
                {t("continueWithSso")}
              </button>
            </div>
          ) : null}

          <label className="block" htmlFor="password">
            <span className="text-site-ink-muted mb-1 block text-xs font-medium">
              {t("password")}
            </span>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
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

          <div className="flex flex-wrap items-center justify-between gap-2">
            {forgotPasswordHref ? (
              <a
                href={forgotPasswordHref}
                className="text-site-ink-muted decoration-site-ink-subtle text-sm font-semibold underline"
              >
                {t("forgotPassword")}
              </a>
            ) : (
              <button
                type="button"
                onClick={handleForgotPasswordPlaceholder}
                className="text-site-ink-muted decoration-site-ink-subtle cursor-pointer text-sm font-semibold underline"
              >
                {t("forgotPassword")}
              </button>
            )}
            <Link
              href="/"
              className="text-site-ink-muted decoration-site-ink-subtle cursor-pointer text-sm font-semibold underline"
            >
              {t("backToHome")}
            </Link>
          </div>

          {/* No self-registration: accounts come from admin invitations, SCIM, or SSO. */}
          <p className="text-site-ink-muted text-sm leading-6">
            {t("noAccountHint")}
          </p>

          {forgotPlaceholderMessage ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
              {forgotPlaceholderMessage}
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
            className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover h-10 w-full cursor-pointer rounded-full px-5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
          >
            {form.formState.isSubmitting ? t("signingIn") : t("signIn")}
          </button>
        </form>

        {hasSsoEntry ? (
          <div className="border-site-border mt-5 border-t pt-5">
            <button
              type="button"
              onClick={handleStartSso}
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
