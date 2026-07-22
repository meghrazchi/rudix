"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuthSession } from "@/lib/use-auth-session";

export default function OnboardingPage() {
  const router = useRouter();
  const { state } = useAuthSession();

  useEffect(() => {
    if (state.status === "unauthenticated") {
      router.replace("/login?next=%2Forganization-onboarding");
      return;
    }

    if (state.status === "authenticated") {
      router.replace("/organization-onboarding");
    }
  }, [router, state.status]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6">
      <div className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 text-center shadow-sm">
        <h1 className="text-2xl font-bold text-[#2a2640]">
          Redirecting to organization onboarding
        </h1>
        <p className="mt-2 text-sm text-[#68647b]">
          Please wait while we route your session.
        </p>
      </div>
    </div>
  );
}
