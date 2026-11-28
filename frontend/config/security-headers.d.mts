export function buildSecurityHeaders(
  env: Record<string, string | undefined>,
  options: { isDev: boolean },
): { key: string; value: string }[];
export function buildContentSecurityPolicy(
  env: Record<string, string | undefined>,
  options: { isDev: boolean },
): string;
export const CSP_HEADER_KEYS: readonly string[];
export function isContentSecurityPolicyHeader(key: string): boolean;
