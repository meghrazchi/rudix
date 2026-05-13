import {
  clearSessionStorage,
  readSessionFromStorage,
  type AuthenticatedSession,
  writeSessionToStorage,
} from "@/lib/auth-session";

export type SessionSnapshot = {
  isAuthenticated: boolean;
  session: AuthenticatedSession | null;
};

export function getSessionSnapshot(): SessionSnapshot {
  const session = readSessionFromStorage();
  return {
    isAuthenticated: session !== null,
    session,
  };
}

export function persistSession(session: AuthenticatedSession): void {
  writeSessionToStorage(session);
}

export function clearSession(): void {
  clearSessionStorage();
}
