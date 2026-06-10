"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Suspense, useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import {
  getSignupProviderLabel,
  getSignupSsoStartHref,
  signupFormSchema,
  startSignupSession,
  type SignupFlowError,
  type SignupFormValues,
} from "@/lib/auth-signup";
import { resolveAuthenticatedNavigationTarget } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";

function safeErrorMessage(error: unknown): string {
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

  return "Signup failed. Please try again.";
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
  return (
    <div
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-2xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <p className="text-sm text-[#68647b]">Loading sign-up...</p>
      </main>
    </div>
  );
}

function SignupPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";
  const { state, setAuthenticatedSession } = useAuthSession();

  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const form = useForm<SignupFormValues>({
    resolver: zodResolver(signupFormSchema),
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
      setAuthenticatedSession(result.session);
      router.replace(
        resolvePostSignupTarget(nextPath, result.nextStep, result.session),
      );
    } catch (error) {
      setSubmissionError(safeErrorMessage(error));
    }
  }

  function handleStartProviderSignup() {
    if (!ssoStartHref) {
      setSubmissionError(
        "Provider signup is configured but no start URL is available.",
      );
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
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6 py-8"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-2xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <div className="mb-2 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Rudix Access
          </p>
        </div>
        <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
          Create your account
        </h1>
        <p className="mb-6 text-sm text-[#68647b]">
          Sign up to create a new workspace or join an existing one and continue
          to onboarding.
        </p>

        <form
          className="space-y-4"
          onSubmit={form.handleSubmit(onSubmit)}
          noValidate
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block" htmlFor="fullName">
              <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Full name
              </span>
              <input
                id="fullName"
                type="text"
                autoComplete="name"
                {...form.register("fullName")}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
              />
            </label>

            <label className="block" htmlFor="email">
              <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Email
              </span>
              <input
                id="email"
                type="email"
                autoComplete="email"
                {...form.register("email")}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
              />
            </label>
          </div>

          {form.formState.errors.fullName?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.fullName.message}
            </p>
          ) : null}
          {form.formState.errors.email?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.email.message}
            </p>
          ) : null}

          <label className="block" htmlFor="password">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Password
            </span>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              {...form.register("password")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
            />
          </label>
          {form.formState.errors.password?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.password.message}
            </p>
          ) : null}

          <fieldset className="rounded-lg border border-[#e0dced] bg-white p-4">
            <legend className="px-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Workspace
            </legend>
            <div className="mt-2 space-y-2">
              <label className="flex items-center gap-2 text-sm text-[#2d2a3f]">
                <input
                  type="radio"
                  value="create"
                  {...form.register("workspaceMode")}
                />
                Create a new workspace
              </label>
              <label className="flex items-center gap-2 text-sm text-[#2d2a3f]">
                <input
                  type="radio"
                  value="join"
                  {...form.register("workspaceMode")}
                />
                Join an existing workspace
              </label>
            </div>

            {workspaceMode === "create" ? (
              <label className="mt-3 block" htmlFor="workspaceName">
                <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Workspace name
                </span>
                <input
                  id="workspaceName"
                  type="text"
                  {...form.register("workspaceName")}
                  className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
                />
              </label>
            ) : (
              <label className="mt-3 block" htmlFor="inviteCode">
                <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Workspace invite code
                </span>
                <input
                  id="inviteCode"
                  type="text"
                  {...form.register("inviteCode")}
                  className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
                />
              </label>
            )}
          </fieldset>

          {form.formState.errors.workspaceName?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.workspaceName.message}
            </p>
          ) : null}
          {form.formState.errors.inviteCode?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.inviteCode.message}
            </p>
          ) : null}

          <label className="flex items-start gap-2 rounded-lg border border-[#e0dced] bg-[#faf8ff] p-3 text-sm text-[#2d2a3f]">
            <input
              type="checkbox"
              {...form.register("acceptTerms")}
              className="mt-0.5"
            />
            <span>I agree to the terms of service and privacy policy.</span>
          </label>
          {form.formState.errors.acceptTerms?.message ? (
            <p role="alert" className="text-xs text-rose-700">
              {form.formState.errors.acceptTerms.message}
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
            className="h-10 w-full rounded-lg bg-[#3525cd] px-5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {form.formState.isSubmitting
              ? "Creating account..."
              : "Create account"}
          </button>
        </form>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <Link
            href="/login"
            className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5]"
          >
            Already have an account? Sign in
          </Link>
          <Link
            href="/"
            className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5]"
          >
            Back to public home
          </Link>
        </div>

        {ssoStartHref ? (
          <div className="mt-5 border-t border-[#e4e1f2] pt-5">
            <button
              type="button"
              onClick={handleStartProviderSignup}
              className="h-10 w-full rounded-lg border border-[#d2cee6] bg-white px-5 text-sm font-semibold text-[#3525cd] transition hover:bg-[#f5f3ff]"
            >
              Continue with {providerLabel}
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}
