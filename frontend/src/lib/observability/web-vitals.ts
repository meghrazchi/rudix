import { SUPPORTED_LOCALES } from "@/i18n/routing";

/** Metrics the backend accepts; anything else Next reports is dropped. */
export const WEB_VITAL_NAMES = ["LCP", "INP", "CLS", "FCP", "TTFB"] as const;
export type WebVitalName = (typeof WEB_VITAL_NAMES)[number];

export type WebVitalRating = "good" | "needs-improvement" | "poor";

export type WebVitalNavigationType =
  | "navigate"
  | "reload"
  | "back-forward"
  | "back-forward-cache"
  | "prerender"
  | "restore";

export type WebVitalSample = {
  name: WebVitalName;
  value: number;
  route: string;
  rating: WebVitalRating;
  navigation_type?: WebVitalNavigationType;
};

/** The subset of Next's `NextWebVitalsMetric` this module reads. */
export type ReportedWebVital = {
  name: string;
  value: number;
  rating?: string;
  navigationType?: string;
};

export const MAX_BATCH_SIZE = 10;

const ID_SEGMENT = "[id]";
const MAX_ROUTE_LENGTH = 121;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const LONG_HEX = /^[0-9a-f]{16,}$/i;
const NUMERIC = /^\d+$/;
const TOKEN_LIKE = /^[A-Za-z0-9_-]{16,}$/;
const ALLOWED_SEGMENT = /^[A-Za-z0-9_-]+$/;

function isIdentifierSegment(segment: string): boolean {
  if (UUID.test(segment) || LONG_HEX.test(segment) || NUMERIC.test(segment)) {
    return true;
  }
  // Long opaque tokens mix letters and digits; slugs such as
  // "organization-onboarding" have no digits and stay as they are.
  return (
    TOKEN_LIKE.test(segment) && /\d/.test(segment) && /[A-Za-z]/.test(segment)
  );
}

/**
 * Turns a concrete pathname into a low-cardinality route pattern: a leading
 * locale becomes `[locale]` and identifier-like segments become `[id]`.
 * Never returns query strings, hashes or raw identifiers.
 */
export function toRoutePattern(pathname: string): string {
  const path = pathname.split(/[?#]/, 1)[0] ?? "";
  const segments = path.split("/").filter((segment) => segment.length > 0);
  const mapped = segments.map((segment, index) => {
    if (
      index === 0 &&
      (SUPPORTED_LOCALES as readonly string[]).includes(segment)
    ) {
      return "[locale]";
    }
    if (isIdentifierSegment(segment) || !ALLOWED_SEGMENT.test(segment)) {
      return ID_SEGMENT;
    }
    return segment;
  });
  const route = `/${mapped.join("/")}`;
  return route.length > MAX_ROUTE_LENGTH
    ? route.slice(0, MAX_ROUTE_LENGTH).replace(/\[[^\]]*$/, "")
    : route;
}

const RATINGS: readonly string[] = ["good", "needs-improvement", "poor"];
const NAVIGATION_TYPES: readonly string[] = [
  "navigate",
  "reload",
  "back-forward",
  "back-forward-cache",
  "prerender",
  "restore",
];

/** A sample the backend will accept, or null for metrics it does not take. */
export function toWebVitalSample(
  metric: ReportedWebVital,
  pathname: string,
): WebVitalSample | null {
  if (!(WEB_VITAL_NAMES as readonly string[]).includes(metric.name)) {
    return null;
  }
  if (!Number.isFinite(metric.value) || metric.value < 0) {
    return null;
  }
  const rating = RATINGS.includes(metric.rating ?? "")
    ? (metric.rating as WebVitalRating)
    : "needs-improvement";
  const sample: WebVitalSample = {
    name: metric.name as WebVitalName,
    value: metric.value,
    route: toRoutePattern(pathname),
    rating,
  };
  if (NAVIGATION_TYPES.includes(metric.navigationType ?? "")) {
    sample.navigation_type = metric.navigationType as WebVitalNavigationType;
  }
  return sample;
}

export type WebVitalsBatcher = {
  add: (sample: WebVitalSample) => void;
  flush: () => void;
  /** Drops anything not yet sent (consent withdrawn, component unmounted). */
  discard: () => void;
};

/** Collects samples, sending at most `MAX_BATCH_SIZE` per call to `send`. */
export function createWebVitalsBatcher(
  send: (samples: WebVitalSample[]) => void,
): WebVitalsBatcher {
  let buffer: WebVitalSample[] = [];

  const flush = () => {
    while (buffer.length > 0) {
      send(buffer.slice(0, MAX_BATCH_SIZE));
      buffer = buffer.slice(MAX_BATCH_SIZE);
    }
  };

  return {
    add(sample) {
      buffer.push(sample);
      if (buffer.length >= MAX_BATCH_SIZE) {
        flush();
      }
    },
    flush,
    discard() {
      buffer = [];
    },
  };
}
