export type AppRole = "owner" | "admin" | "member" | "viewer";

export type AuthenticatedSession = {
  userId: string;
  email: string | null;
  role: AppRole;
  organizationId: string | null;
  organizationName: string | null;
};

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export type SessionState = {
  status: SessionStatus;
  session: AuthenticatedSession | null;
};

const SESSION_STORAGE_KEY = "rudix.session.v1";

function isRole(value: unknown): value is AppRole {
  return value === "owner" || value === "admin" || value === "member" || value === "viewer";
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
    (candidate.organizationId === null || typeof candidate.organizationId === "string") &&
    (candidate.organizationName === null || typeof candidate.organizationName === "string")
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
    return parsed;
  } catch {
    return null;
  }
}

export function writeSessionToStorage(session: AuthenticatedSession): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearSessionStorage(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}
