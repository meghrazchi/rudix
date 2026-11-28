"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";

import { resolveAuthenticatedNavigationTarget } from "@/lib/app-routes";
import { useAuthSession } from "@/lib/use-auth-session";

type CallbackStatus =
  | "loading"
  | "success"
  | "error_missing_token"
  | "error_exchange";

export default function SSOCallbackPage() {
  return (
    <Suspense fallback={<SSOCallbackShell status="loading" message={null} />}>
      <SSOCallbackContent />
    </Suspense>
  );
}

function SSOCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setAuthenticatedSession } = useAuthSession();
  const ran = useRef(false);

  const accessToken = searchParams.get("access_token");
  const userId = searchParams.get("user_id");
  const email = searchParams.get("email");
  const role = searchParams.get("role");
  const organizationId = searchParams.get("organization_id");
  const organizationName = searchParams.get("organization_name");
  const next = searchParams.get("next") || "/dashboard";
  const missingToken = !accessToken || !userId || !email;
  const initialState = missingToken
    ? {
        status: "error_missing_token" as CallbackStatus,
        message:
          "SSO authentication did not return the expected session data. Please try again or contact your administrator.",
      }
    : { status: "loading" as CallbackStatus, message: null as string | null };

  const [status, setStatus] = useState<CallbackStatus>(initialState.status);
  const [message, setMessage] = useState<string | null>(initialState.message);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    if (missingToken) {
      return;
    }

    try {
      setAuthenticatedSession({
        userId,
        email,
        role: (role as "owner" | "admin" | "member" | "viewer") || "member",
        organizationId,
        organizationName,
        accessToken,
        refreshToken: null,
      });
      // The token now lives in memory only (R07-09); drop it from the URL
      // and the history entry before navigating away.
      window.history.replaceState(null, "", window.location.pathname);
      router.replace(
        resolveAuthenticatedNavigationTarget(next, {
          userId,
          email,
          role: (role as "owner" | "admin" | "member" | "viewer") || "member",
          organizationId,
          organizationName,
          accessToken,
          refreshToken: null,
        }),
      );
    } catch {
      // One-time init effect; error state update is unavoidable here.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStatus("error_exchange");
      setMessage(
        "An unexpected error occurred while establishing your session. Please try again.",
      );
    }
  }, [
    accessToken,
    userId,
    email,
    missingToken,
    role,
    organizationId,
    organizationName,
    next,
    router,
    setAuthenticatedSession,
    setMessage,
    setStatus,
  ]);

  return <SSOCallbackShell status={status} message={message} />;
}

function SSOCallbackShell({
  status,
  message,
}: {
  status: CallbackStatus;
  message: string | null;
}) {
  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="border-site-border bg-site-surface w-full max-w-md rounded-3xl border p-8 text-center shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)]">
        <div className="mb-4 flex justify-center">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={32}
            height={32}
            className="h-8 w-8"
          />
        </div>

        {status === "loading" || status === "success" ? (
          <>
            <h1 className="text-site-ink mb-2 text-xl font-bold">
              Completing sign-in…
            </h1>
            <p className="text-site-ink-muted text-sm">
              Verifying your SSO session. You will be redirected shortly.
            </p>
            <div className="mt-4 flex justify-center">
              <span className="border-site-accent inline-block h-5 w-5 animate-spin rounded-full border-2 border-t-transparent" />
            </div>
          </>
        ) : (
          <>
            <h1 className="text-site-ink mb-2 text-xl font-bold">
              SSO sign-in failed
            </h1>
            <p className="text-site-ink-muted text-sm">
              {message ?? "An error occurred. Please try again."}
            </p>
            <Link
              href="/login"
              className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover mt-5 inline-block rounded-full px-5 py-2 text-sm font-semibold transition"
            >
              Back to sign-in
            </Link>
          </>
        )}
      </main>
    </div>
  );
}
