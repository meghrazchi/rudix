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
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Invitation
          </p>
        </div>

        {pageState.status === "form" && (
          <>
            <h1 className="mb-1 text-3xl font-extrabold text-[#2a2640]">
              Accept your invite
            </h1>
            <p className="mb-6 text-sm text-[#68647b]">
              Set a password to activate your account and get started.
            </p>
            <form
              onSubmit={form.handleSubmit(handleSubmit)}
              className="space-y-4"
            >
              <div>
                <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Min 8 characters"
                    autoComplete="new-password"
                    {...form.register("password")}
                    className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 pr-10 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute top-1/2 right-2.5 -translate-y-1/2 text-[#999] hover:text-[#555]"
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
                  <p role="alert" className="mt-1 text-xs text-rose-700">
                    {form.formState.errors.password.message}
                  </p>
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Confirm password
                </label>
                <input
                  type={showPassword ? "text" : "password"}
                  placeholder="Repeat password"
                  autoComplete="new-password"
                  {...form.register("confirm")}
                  className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                />
                {form.formState.errors.confirm && (
                  <p role="alert" className="mt-1 text-xs text-rose-700">
                    {form.formState.errors.confirm.message}
                  </p>
                )}
              </div>
              <button
                type="submit"
                disabled={form.formState.isSubmitting || loggingIn}
                className="mt-2 h-10 w-full rounded-lg bg-[#3525cd] text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
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
            <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
              You&rsquo;re in!
            </h1>
            <p className="mb-6 text-sm text-[#68647b]">
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
              className="inline-flex h-10 items-center rounded-lg bg-[#3525cd] px-5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
            >
              Sign in to continue
            </Link>
          </>
        )}

        {pageState.status === "already_accepted" && (
          <>
            <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
              Already accepted
            </h1>
            <p className="mb-6 text-sm text-[#68647b]">
              This invitation has already been accepted. Sign in to access your
              workspace.
            </p>
            <Link
              href="/login"
              className="inline-flex h-10 items-center rounded-lg bg-[#3525cd] px-5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
            >
              Sign in
            </Link>
          </>
        )}

        {pageState.status === "expired" && (
          <>
            <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
              Invitation expired
            </h1>
            <p className="text-sm text-[#68647b]">
              This invitation link has expired (invitations are valid for 7
              days). Ask your administrator to send a new invite.
            </p>
          </>
        )}

        {pageState.status === "revoked" && (
          <>
            <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
              Invitation revoked
            </h1>
            <p className="text-sm text-[#68647b]">
              This invitation has been revoked. Contact your administrator for a
              new invite.
            </p>
          </>
        )}

        {pageState.status === "invalid" && (
          <>
            <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
              Invalid invitation
            </h1>
            <p className="text-sm text-[#68647b]">
              This invitation link is invalid or has already been used. Contact
              your administrator if you believe this is an error.
            </p>
          </>
        )}

        {pageState.status === "error" && (
          <>
            <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">
              Something went wrong
            </h1>
            <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {pageState.message}
            </p>
            <p className="text-sm text-[#68647b]">
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
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <p className="text-sm text-[#68647b]">Loading&hellip;</p>
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
