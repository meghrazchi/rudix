import type { AuthenticatedSession } from "@/lib/auth-session";

/**
 * In-memory session store (R07-09).
 *
 * The access token lives only in this JavaScript heap object, never in
 * `localStorage`. A reload starts empty and restores the session through the
 * HttpOnly refresh cookie. The state hangs off `globalThis` under a
 * registered symbol so duplicated module instances in one tab (dev HMR,
 * split chunks) share a single store; separate tabs never share it.
 */

export const SESSION_STORE_EVENT_NAME = "rudix:session-storage";

type SessionStoreListener = () => void;

type SessionStoreState = {
  session: AuthenticatedSession | null;
  listeners: Set<SessionStoreListener>;
  restoreClaimed: boolean;
};

const STORE_KEY = Symbol.for("rudix.auth.session-store.v1");

type GlobalWithStore = typeof globalThis & {
  [STORE_KEY]?: SessionStoreState;
};

function getState(): SessionStoreState {
  const target = globalThis as GlobalWithStore;
  let state = target[STORE_KEY];
  if (!state) {
    state = { session: null, listeners: new Set(), restoreClaimed: false };
    target[STORE_KEY] = state;
  }
  return state;
}

function sanitize(session: AuthenticatedSession): AuthenticatedSession {
  const { refreshToken: _refreshToken, ...rest } = session;
  return rest;
}

function notify(type: "updated" | "cleared"): void {
  for (const listener of Array.from(getState().listeners)) {
    listener();
  }
  if (typeof window === "undefined") {
    return;
  }
  // Kept for listeners written against the storage-backed session (0.6.x).
  window.dispatchEvent(
    new CustomEvent(SESSION_STORE_EVENT_NAME, {
      detail: { type, occurredAt: Date.now() },
    }),
  );
}

export function getSession(): AuthenticatedSession | null {
  return getState().session;
}

export function setSession(session: AuthenticatedSession): void {
  getState().session = sanitize(session);
  notify("updated");
}

/**
 * Loads a restored session without notifying listeners. Used while a
 * snapshot is read (render), where notifying would update other components
 * mid-render; readers see the primed value on their next read.
 */
export function primeSession(session: AuthenticatedSession): void {
  getState().session = sanitize(session);
}

export function clearSession(): void {
  const state = getState();
  state.session = null;
  state.restoreClaimed = false;
  notify("cleared");
}

/**
 * Returns `true` the first time it is called after page load (or after
 * `clearSession`), so a stored-session fallback is read once, like the
 * 0.6.x startup read, and not again on every render snapshot.
 */
export function claimRestoreAttempt(): boolean {
  const state = getState();
  if (state.restoreClaimed) {
    return false;
  }
  state.restoreClaimed = true;
  return true;
}

/** Subscribe for `useSyncExternalStore`; returns the unsubscribe function. */
export function subscribe(listener: SessionStoreListener): () => void {
  const { listeners } = getState();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
