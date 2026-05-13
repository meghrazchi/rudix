import { isApiClientError } from "@/lib/api/errors";

const REQUEST_ID_PATTERN = /^[A-Za-z0-9:/._-]+$/;
const MAX_REQUEST_ID_LENGTH = 128;

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function sanitizeRequestId(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  if (!trimmed || trimmed.length > MAX_REQUEST_ID_LENGTH) {
    return null;
  }

  if (!REQUEST_ID_PATTERN.test(trimmed)) {
    return null;
  }

  return trimmed;
}

export function isForbiddenError(error: unknown): boolean {
  if (isApiClientError(error)) {
    return error.status === 403;
  }

  if (typeof error === "object" && error !== null && "status" in error) {
    const status = (error as { status?: unknown }).status;
    return status === 403;
  }

  return false;
}

export function extractRequestIdFromError(error: unknown): string | null {
  if (isApiClientError(error)) {
    return sanitizeRequestId(error.requestId);
  }

  if (typeof error !== "object" || error === null) {
    return null;
  }

  const candidate = error as { requestId?: unknown; request_id?: unknown };
  return sanitizeRequestId(candidate.requestId ?? candidate.request_id ?? null);
}

export type SupportAction = {
  href: string;
  label: string;
};

export function getSupportAction(): SupportAction | null {
  const supportUrl = trimToNull(process.env.NEXT_PUBLIC_SUPPORT_URL);
  if (supportUrl) {
    return {
      href: supportUrl,
      label: "Contact support",
    };
  }

  const supportEmail = trimToNull(process.env.NEXT_PUBLIC_SUPPORT_EMAIL);
  if (!supportEmail) {
    return null;
  }

  return {
    href: `mailto:${supportEmail}`,
    label: "Email support",
  };
}
