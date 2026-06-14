"use client";

import { useCallback, useEffect, useState } from "react";

import {
  defaultSessionState,
  getAuthBoundaryMessageKey,
  readSessionFromStorage,
  SESSION_STORAGE_EVENT_NAME,
  SESSION_STORAGE_KEY,
  subscribeAuthBoundaryEvents,
  type AuthBoundaryEventDetail,
  type AuthenticatedSession,
  type SessionState,
} from "@/lib/auth-session";
import {
  performLogout,
  refreshAccessToken,
  syncSessionRefreshState,
} from "@/lib/api/request";
import { writeSessionToStorage } from "@/lib/auth-session";

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

function readCurrentSessionState(): SessionState {
  const session = readSessionFromStorage();
  if (!session) {
    return { status: "unauthenticated", session: null };
  }
  return { status: "authenticated", session };
}

export function useAuthSession(): UseAuthSessionResult {
  const [state, setState] = useState<SessionState>(defaultSessionState);
  const [boundaryEvent, setBoundaryEvent] =
    useState<AuthBoundaryEventDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      void (async () => {
        const storedSession = readSessionFromStorage();
        if (storedSession) {
          const nextState = {
            status: "authenticated",
            session: storedSession,
          } as SessionState;
          syncSessionRefreshState(nextState.session);
          if (!cancelled) {
            setState(nextState);
          }
          void refreshAccessToken({
            trigger: "startup",
          })
            .then((refreshedSession) => {
              if (cancelled || !refreshedSession) {
                return;
              }
              const refreshedState = {
                status: "authenticated",
                session: refreshedSession,
              } as SessionState;
              syncSessionRefreshState(refreshedState.session);
              setState(refreshedState);
            })
            .catch(() => {
              // Keep the cached session if refresh fails on startup.
            });
          return;
        }

        try {
          const refreshedSession = await refreshAccessToken({
            trigger: "startup",
          });
          if (cancelled) {
            return;
          }
          if (refreshedSession) {
            const nextState = {
              status: "authenticated",
              session: refreshedSession,
            } as SessionState;
            syncSessionRefreshState(nextState.session);
            setState(nextState);
            return;
          }
        } catch {
          // Fall through to unauthenticated state.
        }

        const nextState = {
          status: "unauthenticated",
          session: null,
        } as SessionState;
        syncSessionRefreshState(nextState.session);
        if (!cancelled) {
          setState(nextState);
        }
      })();
    }, 0);

    function applyCurrentSessionFromStorage(): void {
      const nextState = readCurrentSessionState();
      syncSessionRefreshState(nextState.session);
      setState(nextState);
    }

    function onStorage(event: StorageEvent): void {
      if (event.key !== SESSION_STORAGE_KEY) {
        return;
      }
      applyCurrentSessionFromStorage();
    }

    function onSessionStorageEvent(): void {
      applyCurrentSessionFromStorage();
    }

    const unsubscribeBoundaryEvents = subscribeAuthBoundaryEvents((event) => {
      setBoundaryEvent(event);
      applyCurrentSessionFromStorage();
    });

    window.addEventListener("storage", onStorage);
    window.addEventListener(
      SESSION_STORAGE_EVENT_NAME,
      onSessionStorageEvent as EventListener,
    );

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
      unsubscribeBoundaryEvents();
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(
        SESSION_STORAGE_EVENT_NAME,
        onSessionStorageEvent as EventListener,
      );
    };
  }, []);

  const setAuthenticatedSession = useCallback(
    (session: AuthenticatedSession) => {
      writeSessionToStorage(session);
      syncSessionRefreshState(session);
      setBoundaryEvent(null);
      setState({ status: "authenticated", session });
    },
    [],
  );

  const signOut = useCallback(async () => {
    await performLogout({ redirectToLogin: false });
    syncSessionRefreshState(null);
    setState({ status: "unauthenticated", session: null });
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
