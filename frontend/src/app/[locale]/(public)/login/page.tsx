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
import { getAuthBoundaryMessage } from "@/lib/auth-session";
import { resolveAuthenticatedNavigationTarget } from "@/lib/app-routes";
import { useAuthSession } from "@/lib/use-auth-session";

function safeErrorMessage(
  error: unknown,
  fallback: string,
): string {
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
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <p className="text-sm text-[#68647b]">{t("loadingSignIn")}</p>
      </main>
    </div>
  );
}

function LoginPageContent() {
  const t = useTranslations("auth");
  const tValidation = useTranslations("validation");
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";
  const authReason = searchParams.get("reason");
  const {
    state,
    setAuthenticatedSession,
    boundaryMessage,
    clearBoundaryEvent,
  } = useAuthSession();

  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [forgotPlaceholderMessage, setForgotPlaceholderMessage] = useState<
    string | null
  >(null);
  const [ssoDiscovery, setSsoDiscovery] = useState<SSODiscoveryState>({
    status: "idle",
  });

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginFormSchema),
    defaultValues: {
      email: "",
      password: "",
    },
    mode: "onSubmit",
  });

  const authNoticeMessage =
    getAuthBoundaryMessage(authReason) ?? boundaryMessage;
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
    if (authReason || boundaryMessage) {
      clearBoundaryEvent();
    }
  }, [authReason, boundaryMessage, clearBoundaryEvent]);

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
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <div className="mb-2 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            {t("signInLabel")}
          </p>
        </div>
        <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">{t("signIn")}</h1>
        <p className="mb-6 text-sm text-[#68647b]">
          {t("signInDescription")}
        </p>

        {authNoticeMessage ? (
          <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {authNoticeMessage}
          </p>
        ) : null}

        <form
          className="space-y-4"
          onSubmit={form.handleSubmit(onSubmit)}
          noValidate
        >
          <label className="block" htmlFor="email">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("email")}
            </span>
            <input
              id="email"
              type="email"
              autoComplete="email"
              {...form.register("email")}
              onBlur={handleEmailBlur}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            />
          </label>
          {form.formState.errors.email?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.email.message}
            </p>
          ) : null}

          {ssoDiscovery.status === "found" ? (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2.5 text-sm text-indigo-800">
              <p className="font-semibold">
                {t("ssoAvailableFor", { domain: ssoDiscovery.domain })}
              </p>
              <p className="mt-0.5 text-xs text-indigo-600">
                {t("ssoDescription")}
              </p>
              <button
                type="button"
                onClick={() => window.location.assign(ssoDiscovery.redirectUrl)}
                className="mt-2 rounded-lg bg-indigo-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-800"
              >
                {t("continueWithSso")}
              </button>
            </div>
          ) : null}

          <label className="block" htmlFor="password">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("password")}
            </span>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              {...form.register("password")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            />
          </label>
          {form.formState.errors.password?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.password.message}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2">
            {forgotPasswordHref ? (
              <a
                href={forgotPasswordHref}
                className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5]"
              >
                {t("forgotPassword")}
              </a>
            ) : (
              <button
                type="button"
                onClick={handleForgotPasswordPlaceholder}
                className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5] cursor-pointer"
              >
                {t("forgotPassword")}
              </button>
            )}
            <div className="flex items-center gap-3">
              <Link
                href="/signup"
                className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5] cursor-pointer"
              >
                {t("createAccount")}
              </Link>
              <Link
                href="/"
                className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5] cursor-pointer"
              >
                {t("backToHome")}
              </Link>
            </div>
          </div>

          {forgotPlaceholderMessage ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {forgotPlaceholderMessage}
            </p>
          ) : null}

          {submissionError ? (
            <p
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
            >
              {submissionError}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={form.formState.isSubmitting || state.status === "loading"}
            className="h-10 w-full rounded-lg bg-[#3525cd] px-5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
          >
            {form.formState.isSubmitting ? t("signingIn") : t("signIn")}
          </button>
        </form>

        {hasSsoEntry ? (
          <div className="mt-5 border-t border-[#e4e1f2] pt-5">
            <button
              type="button"
              onClick={handleStartSso}
              className="h-10 w-full rounded-lg border border-[#d2cee6] bg-white px-5 text-sm font-semibold text-[#3525cd] transition hover:bg-[#f5f3ff]"
            >
              {t("continueWith", { provider: providerLabel })}
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}
