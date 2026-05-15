"use client";

import { useCallback, useEffect, useState } from "react";

import {
  defaultSessionState,
  getAuthBoundaryMessage,
  readSessionFromStorage,
  SESSION_STORAGE_EVENT_NAME,
  SESSION_STORAGE_KEY,
  subscribeAuthBoundaryEvents,
  type AuthBoundaryEventDetail,
  type AuthenticatedSession,
  type SessionState,
} from "@/lib/auth-session";
import { performLogout, syncSessionRefreshState } from "@/lib/api/request";
import { writeSessionToStorage } from "@/lib/auth-session";

type UseAuthSessionResult = {
  state: SessionState;
  boundaryEvent: AuthBoundaryEventDetail | null;
  boundaryMessage: string | null;
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
    const timeoutId = window.setTimeout(() => {
      const nextState = readCurrentSessionState();
      syncSessionRefreshState(nextState.session);
      setState(nextState);
    }, 0);

    function applyCurrentSessionFromStorage() {
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
    boundaryMessage: getAuthBoundaryMessage(boundaryEvent?.reason),
    setAuthenticatedSession,
    signOut,
    clearBoundaryEvent,
  };
}
