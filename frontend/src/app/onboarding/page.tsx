"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuthSession } from "@/lib/use-auth-session";

export default function OnboardingPage() {
  const router = useRouter();
  const { state } = useAuthSession();

  useEffect(() => {
    if (state.status === "unauthenticated") {
      router.replace("/login?next=%2Fonboarding");
    }
  }, [router, state.status]);

  if (state.status !== "authenticated") {
    return (
      <div
        className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6"
        style={{ fontFamily: "Inter, system-ui, sans-serif" }}
      >
        <div className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 text-center shadow-sm">
          <h1 className="text-2xl font-bold text-[#2a2640]">Preparing onboarding</h1>
          <p className="mt-2 text-sm text-[#68647b]">Checking your session before workspace setup.</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-2xl rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Onboarding</p>
        <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">Workspace onboarding</h1>
        <p className="mb-6 text-sm text-[#68647b]">
          Your account is ready. Next, finalize organization settings and member invites.
        </p>

        <div className="rounded-xl border border-[#e0dced] bg-[#faf8ff] p-4 text-sm text-[#2d2a3f]">
          Onboarding workflow screens will be added in the next frontend milestone.
        </div>

        <div className="mt-6 flex gap-3">
          <Link
            href="/dashboard"
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            Continue to dashboard
          </Link>
        </div>
      </main>
    </div>
  );
}
