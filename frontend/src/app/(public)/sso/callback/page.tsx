"use client";

import { Suspense, useEffect, useRef, useState } from "react";
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
  const [status, setStatus] = useState<CallbackStatus>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const ran = useRef(false);

  const accessToken = searchParams.get("access_token");
  const userId = searchParams.get("user_id");
  const email = searchParams.get("email");
  const role = searchParams.get("role");
  const organizationId = searchParams.get("organization_id");
  const organizationName = searchParams.get("organization_name");
  const next = searchParams.get("next") || "/dashboard";

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    if (!accessToken || !userId || !email) {
      setStatus("error_missing_token");
      setMessage(
        "SSO authentication did not return the expected session data. Please try again or contact your administrator.",
      );
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
      setStatus("success");
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
      setStatus("error_exchange");
      setMessage("An unexpected error occurred while establishing your session. Please try again.");
    }
  }, [
    accessToken,
    userId,
    email,
    role,
    organizationId,
    organizationName,
    next,
    router,
    setAuthenticatedSession,
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
      className="rudix-auth-pattern flex min-h-screen items-center justify-center px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm text-center">
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
            <h1 className="mb-2 text-xl font-bold text-[#2a2640]">
              Completing sign-in…
            </h1>
            <p className="text-sm text-[#68647b]">
              Verifying your SSO session. You will be redirected shortly.
            </p>
            <div className="mt-4 flex justify-center">
              <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-[#3525cd] border-t-transparent" />
            </div>
          </>
        ) : (
          <>
            <h1 className="mb-2 text-xl font-bold text-[#2a2640]">
              SSO sign-in failed
            </h1>
            <p className="text-sm text-[#68647b]">
              {message ?? "An error occurred. Please try again."}
            </p>
            <a
              href="/login"
              className="mt-5 inline-block rounded-lg bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] transition"
            >
              Back to sign-in
            </a>
          </>
        )}
      </main>
    </div>
  );
}
