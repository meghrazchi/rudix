"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import {
  getAuthBoundaryMessageKey,
  readSessionFromStorage,
  subscribeAuthBoundaryEvents,
  writeSessionToStorage,
  type AuthBoundaryEventDetail,
  type AuthenticatedSession,
  type SessionState,
} from "@/lib/auth-session";
import {
  clearSession as clearStoredSession,
  getSession as getStoredSession,
  subscribe as subscribeToSessionStore,
} from "@/lib/auth/session-store";
import {
  performLogout,
  refreshAccessToken,
  syncSessionRefreshState,
} from "@/lib/api/request";

type UseAuthSessionResult = {
  state: SessionState;
  boundaryEvent: AuthBoundaryEventDetail | null;
  boundaryMessageKey:
    | "signedOut"
    | "sessionExpired"
    | "sessionRevoked"
    | "sessionInvalid"
    | null;
  setAuthenticatedSession: (session: AuthenticatedSession) => void;
  signOut: () => Promise<void>;
  clearBoundaryEvent: () => void;
};

function getServerSessionSnapshot(): AuthenticatedSession | null {
  return null;
}

/**
 * Session state over the in-memory store (R07-09). The status is `loading`
 * until the startup refresh settles when no session is in memory; a session
 * already in memory (client navigation, legacy restore) is authenticated at
 * once and refreshed in the background, as in 0.6.x.
 */
export function useAuthSession(): UseAuthSessionResult {
  const session = useSyncExternalStore(
    subscribeToSessionStore,
    readSessionFromStorage,
    getServerSessionSnapshot,
  );
  const [bootstrapped, setBootstrapped] = useState(false);
  const [boundaryEvent, setBoundaryEvent] =
    useState<AuthBoundaryEventDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      const storedSession = readSessionFromStorage();
      syncSessionRefreshState(storedSession);
      if (storedSession) {
        setBootstrapped(true);
      }
      void refreshAccessToken({ trigger: "startup" })
        .then((refreshedSession) => {
          if (!cancelled && refreshedSession) {
            syncSessionRefreshState(refreshedSession);
          }
        })
        .catch(() => {
          // Keep a cached session if refresh fails on startup; without one
          // the state falls through to unauthenticated.
        })
        .finally(() => {
          if (!cancelled) {
            setBootstrapped(true);
          }
        });
    }, 0);

    const unsubscribeBoundaryEvents = subscribeAuthBoundaryEvents((event) => {
      setBoundaryEvent(event);
      // Another tab signed out or lost its session (storage event): drop
      // this tab's in-memory copy too. In this tab it is already cleared.
      if (getStoredSession()) {
        clearStoredSession();
      }
      syncSessionRefreshState(null);
    });

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
      unsubscribeBoundaryEvents();
    };
  }, []);

  const state = useMemo<SessionState>(() => {
    if (session) {
      return { status: "authenticated", session };
    }
    return {
      status: bootstrapped ? "unauthenticated" : "loading",
      session: null,
    };
  }, [bootstrapped, session]);

  const setAuthenticatedSession = useCallback(
    (nextSession: AuthenticatedSession) => {
      writeSessionToStorage(nextSession);
      syncSessionRefreshState(nextSession);
      setBoundaryEvent(null);
      setBootstrapped(true);
    },
    [],
  );

  const signOut = useCallback(async () => {
    await performLogout({ redirectToLogin: false });
    syncSessionRefreshState(null);
    setBootstrapped(true);
  }, []);

  const clearBoundaryEvent = useCallback(() => {
    setBoundaryEvent(null);
  }, []);

  return {
    state,
    boundaryEvent,
    boundaryMessageKey: getAuthBoundaryMessageKey(boundaryEvent?.reason),
    setAuthenticatedSession,
    signOut,
    clearBoundaryEvent,
  };
}
