"use client";

import { useEffect } from "react";

import {
  addFrontendBreadcrumb,
  captureFrontendException,
} from "@/lib/observability";

/** Records a breadcrumb and sends the error to the configured monitoring. */
export function useReportRouteError(error: Error & { digest?: string }): void {
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
}
