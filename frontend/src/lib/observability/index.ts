import {
  captureFrontendException as captureSentryException,
  isFrontendMonitoringEnabled as isSentryEnabled,
  pushFrontendBreadcrumb,
} from "@/lib/observability/sentry";
import type {
  FrontendBreadcrumb,
  FrontendObservabilityContext,
} from "@/lib/observability/types";

export { redactObservabilityValue } from "@/lib/observability/redaction";
export { resetFrontendBreadcrumbsForTesting } from "@/lib/observability/sentry";
export type {
  FrontendBreadcrumb,
  FrontendObservabilityContext,
  ObservabilityLevel,
} from "@/lib/observability/types";

export function isFrontendMonitoringEnabled(): boolean {
  return isSentryEnabled();
}

export function addFrontendBreadcrumb(breadcrumb: FrontendBreadcrumb): void {
  pushFrontendBreadcrumb(breadcrumb);
}

export async function captureFrontendException(
  error: unknown,
  context?: FrontendObservabilityContext,
): Promise<void> {
  await captureSentryException(error, context);
}
