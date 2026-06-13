export type AppRole =
  | "owner"
  | "admin"
  | "member"
  | "viewer"
  | "reviewer"
  | "developer"
  | "security_admin"
  | "billing_admin";

export type AuthenticatedSession = {
  userId: string;
  email: string | null;
  role: AppRole;
  organizationId: string | null;
  organizationName: string | null;
  accessToken?: string | null;
  refreshToken?: string | null;
};

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export type SessionState = {
  status: SessionStatus;
  session: AuthenticatedSession | null;
};

export type AuthBoundaryReason =
  | "signed_out"
  | "session_expired"
  | "session_revoked"
  | "session_invalid"
  | "session_refresh_failed";

export type AuthBoundaryEventDetail = {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  redirectTo: string;
  occurredAt: number;
};

export const SESSION_STORAGE_KEY = "rudix.session.v1";
export const AUTH_BOUNDARY_STORAGE_KEY = "rudix.auth.boundary.v1";
export const AUTH_BOUNDARY_EVENT_NAME = "rudix:auth-boundary";
export const SESSION_STORAGE_EVENT_NAME = "rudix:session-storage";

const VALID_ROLES: ReadonlySet<string> = new Set([
  "owner",
  "admin",
  "member",
  "viewer",
  "reviewer",
  "developer",
  "security_admin",
  "billing_admin",
]);

function isRole(value: unknown): value is AppRole {
  return typeof value === "string" && VALID_ROLES.has(value);
}

function isValidSession(value: unknown): value is AuthenticatedSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<AuthenticatedSession>;
  return (
    typeof candidate.userId === "string" &&
    candidate.userId.trim().length > 0 &&
    isRole(candidate.role) &&
    (candidate.email === null || typeof candidate.email === "string") &&
    (candidate.organizationId === null ||
      typeof candidate.organizationId === "string") &&
    (candidate.organizationName === null ||
      typeof candidate.organizationName === "string") &&
    (candidate.accessToken === undefined ||
      candidate.accessToken === null ||
      typeof candidate.accessToken === "string") &&
    (candidate.refreshToken === undefined ||
      candidate.refreshToken === null ||
      typeof candidate.refreshToken === "string")
  );
}

export function defaultSessionState(): SessionState {
  return {
    status: "loading",
    session: null,
  };
}

export function readSessionFromStorage(): AuthenticatedSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed: unknown = JSON.parse(raw);
    if (!isValidSession(parsed)) {
      return null;
    }
    const session = parsed as AuthenticatedSession;
    if ("refreshToken" in (parsed as Record<string, unknown>)) {
      writeSessionToStorage(session);
    }
    return session;
  } catch {
    return null;
  }
}

export function writeSessionToStorage(session: AuthenticatedSession): void {
  if (typeof window === "undefined") {
    return;
  }
  const { refreshToken: _refreshToken, ...sanitizedSession } = session;
  window.localStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify(sanitizedSession),
  );
  window.dispatchEvent(
    new CustomEvent(SESSION_STORAGE_EVENT_NAME, {
      detail: { type: "updated", occurredAt: Date.now() },
    }),
  );
}

export function clearSessionStorage(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
  window.dispatchEvent(
    new CustomEvent(SESSION_STORAGE_EVENT_NAME, {
      detail: { type: "cleared", occurredAt: Date.now() },
    }),
  );
}

function normalizeNextPath(path: string | null | undefined): string | null {
  if (!path) {
    return null;
  }

  const trimmed = path.trim();
  if (!trimmed.startsWith("/")) {
    return null;
  }
  if (trimmed.startsWith("/login")) {
    return null;
  }
  return trimmed;
}

export function buildLoginRedirectUrl(params: {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  nextPath?: string | null;
}): string {
  const query = new URLSearchParams();
  query.set("reason", params.reason);

  if (params.preserveNextPath) {
    const normalizedNext = normalizeNextPath(params.nextPath);
    if (normalizedNext) {
      query.set("next", normalizedNext);
    }
  }

  return `/login?${query.toString()}`;
}

export function getAuthBoundaryMessageKey(
  reason: string | null | undefined,
): "signedOut" | "sessionExpired" | "sessionRevoked" | "sessionInvalid" | null {
  if (reason === "signed_out") return "signedOut";
  if (reason === "session_expired") return "sessionExpired";
  if (reason === "session_revoked") return "sessionRevoked";
  if (reason === "session_invalid" || reason === "session_refresh_failed")
    return "sessionInvalid";
  return null;
}

export function emitAuthBoundaryEvent(params: {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  nextPath?: string | null;
}): AuthBoundaryEventDetail {
  const redirectTo = buildLoginRedirectUrl({
    reason: params.reason,
    preserveNextPath: params.preserveNextPath,
    nextPath: params.nextPath,
  });

  const detail: AuthBoundaryEventDetail = {
    reason: params.reason,
    preserveNextPath: params.preserveNextPath,
    redirectTo,
    occurredAt: Date.now(),
  };

  if (typeof window === "undefined") {
    return detail;
  }

  try {
    window.dispatchEvent(
      new CustomEvent<AuthBoundaryEventDetail>(AUTH_BOUNDARY_EVENT_NAME, {
        detail,
      }),
    );
    window.localStorage.setItem(
      AUTH_BOUNDARY_STORAGE_KEY,
      JSON.stringify({
        ...detail,
        nonce: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      }),
    );
  } catch {
    // Ignore browser storage/event failures.
  }

  return detail;
}

export function subscribeAuthBoundaryEvents(
  onBoundaryEvent: (event: AuthBoundaryEventDetail) => void,
): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  function onWindowEvent(event: Event): void {
    const custom = event as CustomEvent<AuthBoundaryEventDetail>;
    if (!custom.detail) {
      return;
    }
    onBoundaryEvent(custom.detail);
  }

  function onStorageEvent(event: StorageEvent): void {
    if (event.key !== AUTH_BOUNDARY_STORAGE_KEY || !event.newValue) {
      return;
    }

    try {
      const parsed = JSON.parse(
        event.newValue,
      ) as Partial<AuthBoundaryEventDetail>;
      if (
        typeof parsed.reason !== "string" ||
        typeof parsed.preserveNextPath !== "boolean" ||
        typeof parsed.redirectTo !== "string" ||
        typeof parsed.occurredAt !== "number"
      ) {
        return;
      }

      onBoundaryEvent({
        reason: parsed.reason as AuthBoundaryReason,
        preserveNextPath: parsed.preserveNextPath,
        redirectTo: parsed.redirectTo,
        occurredAt: parsed.occurredAt,
      });
    } catch {
      // Ignore malformed events.
    }
  }

  window.addEventListener(
    AUTH_BOUNDARY_EVENT_NAME,
    onWindowEvent as EventListener,
  );
  window.addEventListener("storage", onStorageEvent);

  return () => {
    window.removeEventListener(
      AUTH_BOUNDARY_EVENT_NAME,
      onWindowEvent as EventListener,
    );
    window.removeEventListener("storage", onStorageEvent);
  };
}
