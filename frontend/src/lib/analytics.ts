declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

export type OnboardingEventName =
  | "onboarding_step_complete"
  | "onboarding_step_skipped"
  | "onboarding_dismissed"
  | "onboarding_tour_started"
  | "onboarding_tour_completed"
  | "onboarding_reset"
  | "onboarding_sample_docs_loaded";

export function trackOnboardingEvent(
  eventName: OnboardingEventName,
  params?: Record<string, string | number | boolean>,
): void {
  if (typeof window === "undefined" || typeof window.gtag !== "function") {
    return;
  }
  window.gtag("event", eventName, {
    event_category: "onboarding",
    ...params,
  });
}
