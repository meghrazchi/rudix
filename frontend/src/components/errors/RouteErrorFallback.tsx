"use client";

import { useEffect } from "react";

import Link from "next/link";

import {
  addFrontendBreadcrumb,
  captureFrontendException,
} from "@/lib/observability";

type AppRouteErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function AppRouteError({ error, reset }: AppRouteErrorProps) {
  useEffect(() => {
    const route =
      typeof window !== "undefined" ? window.location.pathname : null;

    addFrontendBreadcrumb({
      category: "route.error",
      message: "Route-level rendering error captured",
      level: "error",
      data: {
        route,
        digest: error.digest ?? null,
      },
    });

    void captureFrontendException(error, {
      feature: "route.render",
      route: route ?? undefined,
      level: "error",
      tags: {
        error_digest: error.digest ?? "unknown",
      },
      extra: {
        error_name: error.name,
        error_message: error.message,
      },
    });
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6">
      <section className="w-full max-w-xl rounded-2xl border border-[#dad8ef] bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-bold text-[#29263f]">
          Unable to render this page
        </h1>
        <p className="mt-3 text-sm text-[#5f5b76]">
          A runtime error interrupted rendering. You can retry this view or
          navigate back to the dashboard.
        </p>
        {error.digest ? (
          <p className="mt-2 text-xs text-[#7a7692]">
            Error reference:{" "}
            <span className="font-mono font-semibold">{error.digest}</span>
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={reset}
            className="rounded-md bg-[#3346d3] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b3cc0]"
          >
            Retry
          </button>
          <Link
            href="/dashboard"
            className="rounded-md border border-[#cbc8e6] px-4 py-2 text-sm font-semibold text-[#342f5c] hover:bg-[#f7f6ff]"
          >
            Back to dashboard
          </Link>
        </div>
      </section>
    </main>
  );
}
