"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import type { AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";

const roleOptions: AppRole[] = ["owner", "admin", "member", "viewer"];

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";
  const { state, setAuthenticatedSession } = useAuthSession();

  const [userId, setUserId] = useState("demo-user-001");
  const [email, setEmail] = useState("demo@rudix.local");
  const [organizationId, setOrganizationId] = useState("demo-org-001");
  const [organizationName, setOrganizationName] = useState("Demo Organization");
  const [role, setRole] = useState<AppRole>("member");

  useEffect(() => {
    if (state.status === "authenticated") {
      router.replace(nextPath);
    }
  }, [nextPath, router, state.status]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthenticatedSession({
      userId: userId.trim(),
      email: email.trim() || null,
      role,
      organizationId: organizationId.trim() || null,
      organizationName: organizationName.trim() || null,
    });
    router.replace(nextPath);
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-7 shadow-sm">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Access</p>
        <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">Sign in</h1>
        <p className="mb-6 text-sm text-[#68647b]">
          Session bootstrap for local product pages. Protected routes will redirect here when authentication is missing.
        </p>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#6a6780]">User ID</span>
            <input
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              required
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
            />
          </label>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Role</span>
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as AppRole)}
                className="h-10 w-full rounded-lg border border-[#d2cee6] bg-white px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
              >
                {roleOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                Organization ID
              </span>
              <input
                value={organizationId}
                onChange={(event) => setOrganizationId(event.target.value)}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
              />
            </label>
          </div>

          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Organization Name
            </span>
            <input
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
            />
          </label>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <button
              type="submit"
              className="h-10 rounded-lg bg-[#3525cd] px-5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
            >
              Continue
            </button>
            <Link href="/" className="text-sm font-semibold text-[#4a438e] underline decoration-[#bdb7e5]">
              Back to public home
            </Link>
          </div>
        </form>
      </main>
    </div>
  );
}
