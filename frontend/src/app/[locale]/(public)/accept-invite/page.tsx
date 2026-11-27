"use client";

import Image from "next/image";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { acceptInvitation } from "@/lib/api/team-invitations";
import { startLoginSession } from "@/lib/auth-login";
import { writeSessionToStorage } from "@/lib/auth-session";

const schema = z
  .object({
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .max(128),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });
type FormValues = z.infer<typeof schema>;

type PageState =
  | { status: "form" }
  | { status: "success"; email: string; orgName: string | null; role: string }
  | { status: "already_accepted" }
  | { status: "expired" }
  | { status: "revoked" }
  | { status: "invalid" }
  | { status: "error"; message: string };

function AcceptInviteContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token");

  const [pageState, setPageState] = useState<PageState>(
    token ? { status: "form" } : { status: "invalid" },
  );
  const [showPassword, setShowPassword] = useState(false);
  const [loggingIn, setLoggingIn] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirm: "" },
  });

  async function handleSubmit(values: FormValues) {
    if (!token) {
      setPageState({ status: "invalid" });
      return;
    }

    try {
      const data = await acceptInvitation(token, values.password);

      // Auto-login with the newly set password
      setLoggingIn(true);
      try {
        const session = await startLoginSession({
          email: data.email,
          password: values.password,
        });
        writeSessionToStorage(session);
        router.replace("/dashboard");
        return;
      } catch {
        // Login failed — still show success so they can sign in manually
        setLoggingIn(false);
      }

      setPageState({
        status: "success",
        email: data.email,
        orgName: data.organization_name,
        role: data.role,
      });
    } catch (err: unknown) {
      const httpStatus =
        err && typeof err === "object" && "status" in err
          ? (err as { status?: number }).status
          : null;
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message?: unknown }).message)
          : "";

      if (httpStatus === 409) setPageState({ status: "already_accepted" });
      else if (httpStatus === 410) {
        setPageState({
          status: message.toLowerCase().includes("revoked")
            ? "revoked"
            : "expired",
        });
      } else if (httpStatus === 404) setPageState({ status: "invalid" });
      else {
        setPageState({
          status: "error",
          message:
            message ||
            "Something went wrong. Please try again or contact your administrator.",
        });
      }
    }
  }

  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="border-site-border bg-site-surface w-full max-w-xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <div className="mb-5 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-site-ink-muted text-xs font-bold tracking-[0.18em] uppercase">
            Invitation
          </p>
        </div>

        {pageState.status === "form" && (
          <>
            <h1 className="text-site-ink mb-1 text-3xl font-semibold tracking-tight">
              Accept your invite
            </h1>
            <p className="text-site-ink-muted mb-6 text-sm">
              Set a password to activate your account and get started.
            </p>
            <form
              onSubmit={form.handleSubmit(handleSubmit)}
              className="space-y-4"
            >
              <div>
                <label className="text-site-ink-muted mb-1 block text-xs font-medium">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Min 8 characters"
                    autoComplete="new-password"
                    {...form.register("password")}
                    className="border-site-border text-site-ink focus:border-site-accent focus:ring-site-accent/10 h-10 w-full rounded-lg border px-3 pr-10 text-sm outline-none focus:ring-2"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="text-site-ink-subtle hover:text-site-ink-muted absolute top-1/2 right-2.5 -translate-y-1/2"
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                  >
                    {showPassword ? (
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                        <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                        <line x1="1" y1="1" x2="23" y2="23" />
                      </svg>
                    ) : (
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
                {form.formState.errors.password && (
                  <p
                    role="alert"
                    className="mt-1 text-xs text-rose-700 dark:text-rose-300"
                  >
                    {form.formState.errors.password.message}
                  </p>
                )}
              </div>
              <div>
                <label className="text-site-ink-muted mb-1 block text-xs font-medium">
                  Confirm password
                </label>
                <input
                  type={showPassword ? "text" : "password"}
                  placeholder="Repeat password"
                  autoComplete="new-password"
                  {...form.register("confirm")}
                  className="border-site-border text-site-ink focus:border-site-accent focus:ring-site-accent/10 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2"
                />
                {form.formState.errors.confirm && (
                  <p
                    role="alert"
                    className="mt-1 text-xs text-rose-700 dark:text-rose-300"
                  >
                    {form.formState.errors.confirm.message}
                  </p>
                )}
              </div>
              <button
                type="submit"
                disabled={form.formState.isSubmitting || loggingIn}
                className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover mt-2 h-10 w-full rounded-full text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              >
                {form.formState.isSubmitting
                  ? "Accepting…"
                  : loggingIn
                    ? "Signing in…"
                    : "Accept & set password"}
              </button>
            </form>
          </>
        )}

        {pageState.status === "success" && (
          <>
            <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
              You&rsquo;re in!
            </h1>
            <p className="text-site-ink-muted mb-6 text-sm">
              Your invitation has been accepted. You&rsquo;ve joined
              {pageState.orgName ? (
                <>
                  {" "}
                  <strong>{pageState.orgName}</strong>
                </>
              ) : (
                " the organization"
              )}{" "}
              as <strong>{pageState.role}</strong>.
            </p>
            <Link
              href="/login"
              className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold transition"
            >
              Sign in to continue
            </Link>
          </>
        )}

        {pageState.status === "already_accepted" && (
          <>
            <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
              Already accepted
            </h1>
            <p className="text-site-ink-muted mb-6 text-sm">
              This invitation has already been accepted. Sign in to access your
              workspace.
            </p>
            <Link
              href="/login"
              className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold transition"
            >
              Sign in
            </Link>
          </>
        )}

        {pageState.status === "expired" && (
          <>
            <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
              Invitation expired
            </h1>
            <p className="text-site-ink-muted text-sm">
              This invitation link has expired (invitations are valid for 7
              days). Ask your administrator to send a new invite.
            </p>
          </>
        )}

        {pageState.status === "revoked" && (
          <>
            <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
              Invitation revoked
            </h1>
            <p className="text-site-ink-muted text-sm">
              This invitation has been revoked. Contact your administrator for a
              new invite.
            </p>
          </>
        )}

        {pageState.status === "invalid" && (
          <>
            <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
              Invalid invitation
            </h1>
            <p className="text-site-ink-muted text-sm">
              This invitation link is invalid or has already been used. Contact
              your administrator if you believe this is an error.
            </p>
          </>
        )}

        {pageState.status === "error" && (
          <>
            <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
              Something went wrong
            </h1>
            <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
              {pageState.message}
            </p>
            <p className="text-site-ink-muted text-sm">
              Please try again or contact your administrator.
            </p>
          </>
        )}
      </main>
    </div>
  );
}

function AcceptInviteFallback() {
  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="border-site-border bg-site-surface w-full max-w-xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <p className="text-site-ink-muted text-sm">Loading&hellip;</p>
      </main>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<AcceptInviteFallback />}>
      <AcceptInviteContent />
    </Suspense>
  );
}
