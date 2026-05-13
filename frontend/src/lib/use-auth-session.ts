"use client";

import { useCallback, useEffect, useState } from "react";

import {
  clearSessionStorage,
  defaultSessionState,
  readSessionFromStorage,
  type AuthenticatedSession,
  type SessionState,
} from "@/lib/auth-session";
import { writeSessionToStorage } from "@/lib/auth-session";

type UseAuthSessionResult = {
  state: SessionState;
  setAuthenticatedSession: (session: AuthenticatedSession) => void;
  signOut: () => void;
};

export function useAuthSession(): UseAuthSessionResult {
  const [state, setState] = useState<SessionState>(defaultSessionState);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const session = readSessionFromStorage();
      if (session) {
        setState({ status: "authenticated", session });
        return;
      }
      setState({ status: "unauthenticated", session: null });
    }, 0);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, []);

  const setAuthenticatedSession = useCallback((session: AuthenticatedSession) => {
    writeSessionToStorage(session);
    setState({ status: "authenticated", session });
  }, []);

  const signOut = useCallback(() => {
    clearSessionStorage();
    setState({ status: "unauthenticated", session: null });
  }, []);

  return {
    state,
    setAuthenticatedSession,
    signOut,
  };
}
