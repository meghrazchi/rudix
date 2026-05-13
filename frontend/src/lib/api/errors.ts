export type ApiErrorCode =
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "content_too_large"
  | "unsupported_media_type"
  | "rate_limited"
  | "service_unavailable"
  | "network_error"
  | "unknown_error"
  | string;

export type ApiErrorMeta = {
  userMessage: string;
  actionMessage: string | null;
  retryable: boolean;
  defaultCode: ApiErrorCode;
};

const DEFAULT_ERROR_META: ApiErrorMeta = {
  userMessage: "Something went wrong while contacting the API.",
  actionMessage: "Try again.",
  retryable: false,
  defaultCode: "unknown_error",
};

const STATUS_ERROR_META: Record<number, ApiErrorMeta> = {
  0: {
    userMessage: "Network request failed.",
    actionMessage: "Check your connection and try again.",
    retryable: true,
    defaultCode: "network_error",
  },
  401: {
    userMessage: "Your session is not valid.",
    actionMessage: "Sign in again.",
    retryable: false,
    defaultCode: "unauthorized",
  },
  403: {
    userMessage: "You do not have permission for this action.",
    actionMessage: "Switch organization or contact an administrator.",
    retryable: false,
    defaultCode: "forbidden",
  },
  404: {
    userMessage: "The requested resource was not found.",
    actionMessage: "Refresh and verify the selected resource.",
    retryable: false,
    defaultCode: "not_found",
  },
  409: {
    userMessage: "The request conflicts with current state.",
    actionMessage: "Refresh the page and try again.",
    retryable: false,
    defaultCode: "conflict",
  },
  413: {
    userMessage: "The uploaded file is too large.",
    actionMessage: "Reduce file size and retry.",
    retryable: false,
    defaultCode: "content_too_large",
  },
  415: {
    userMessage: "The uploaded file type is not supported.",
    actionMessage: "Use a supported file type and retry.",
    retryable: false,
    defaultCode: "unsupported_media_type",
  },
  429: {
    userMessage: "Too many requests were sent.",
    actionMessage: "Wait a moment, then retry.",
    retryable: true,
    defaultCode: "rate_limited",
  },
  503: {
    userMessage: "The service is temporarily unavailable.",
    actionMessage: "Retry shortly.",
    retryable: true,
    defaultCode: "service_unavailable",
  },
};

export type NormalizedBackendError = {
  code: string | null;
  message: string | null;
  details: unknown;
};

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function normalizeBackendError(payload: unknown): NormalizedBackendError {
  const envelope = asRecord(payload);
  if (!envelope) {
    return {
      code: null,
      message: asNonEmptyString(payload),
      details: payload,
    };
  }

  const detail = envelope.detail;
  const detailRecord = asRecord(detail);

  const code =
    asNonEmptyString(envelope.code) ??
    asNonEmptyString(envelope.error) ??
    asNonEmptyString(detailRecord?.code) ??
    asNonEmptyString(detailRecord?.error) ??
    null;

  const message =
    asNonEmptyString(envelope.message) ??
    asNonEmptyString(envelope.detail) ??
    asNonEmptyString(detailRecord?.message) ??
    asNonEmptyString(detailRecord?.detail) ??
    null;

  return {
    code,
    message,
    details: detail ?? payload,
  };
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly details: unknown;
  readonly requestId: string | null;
  readonly userMessage: string;
  readonly actionMessage: string | null;
  readonly retryable: boolean;

  constructor(params: {
    status: number;
    code: ApiErrorCode;
    message: string;
    details: unknown;
    requestId: string | null;
    userMessage: string;
    actionMessage: string | null;
    retryable: boolean;
  }) {
    super(params.message);
    this.name = "ApiClientError";
    this.status = params.status;
    this.code = params.code;
    this.details = params.details;
    this.requestId = params.requestId;
    this.userMessage = params.userMessage;
    this.actionMessage = params.actionMessage;
    this.retryable = params.retryable;
  }
}

function resolveErrorMeta(status: number): ApiErrorMeta {
  return STATUS_ERROR_META[status] ?? DEFAULT_ERROR_META;
}

export function normalizeApiError(params: {
  status: number;
  payload: unknown;
  requestId?: string | null;
  fallbackMessage?: string;
}): ApiClientError {
  const normalized = normalizeBackendError(params.payload);
  const meta = resolveErrorMeta(params.status);

  return new ApiClientError({
    status: params.status,
    code: normalized.code ?? meta.defaultCode,
    message: normalized.message ?? params.fallbackMessage ?? `Request failed (${params.status})`,
    details: normalized.details,
    requestId: params.requestId ?? null,
    userMessage: meta.userMessage,
    actionMessage: meta.actionMessage,
    retryable: meta.retryable,
  });
}

export function normalizeNetworkError(error: unknown): ApiClientError {
  const message = error instanceof Error ? error.message : "Network request failed";
  return new ApiClientError({
    status: 0,
    code: "network_error",
    message,
    details: null,
    requestId: null,
    userMessage: STATUS_ERROR_META[0].userMessage,
    actionMessage: STATUS_ERROR_META[0].actionMessage,
    retryable: true,
  });
}

export function isApiClientError(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError;
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.actionMessage) {
      return `${error.userMessage} ${error.actionMessage}`;
    }
    return error.userMessage;
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return DEFAULT_ERROR_META.userMessage;
}
