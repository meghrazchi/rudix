import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearSessionStorage,
  DEV_SESSION_STORAGE_KEY,
  discardLegacySessionStorage,
  isDevSessionPersistenceEnabled,
  LEGACY_SESSION_STORAGE_KEY,
  readSessionFromStorage,
  SESSION_STORAGE_EVENT_NAME,
  writeSessionToStorage,
} from "@/lib/auth-session";
import {
  clearSession,
  getSession,
  primeSession,
  setSession,
  subscribe,
} from "@/lib/auth/session-store";

const session = {
  userId: "user-1",
  email: "user@example.com",
  role: "member" as const,
  organizationId: "org-1",
  organizationName: "Org One",
  accessToken: "access-token-1",
};

describe("in-memory session store (R07-09)", () => {
  beforeEach(() => {
    clearSession();
  });

  it("stores a sanitized copy and notifies subscribers", () => {
    const listener = vi.fn();
    const events = vi.fn();
    window.addEventListener(SESSION_STORAGE_EVENT_NAME, events);
    const unsubscribe = subscribe(listener);

    setSession({ ...session, refreshToken: "refresh-1" });

    expect(getSession()).toEqual(session);
    expect(getSession()).not.toHaveProperty("refreshToken");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(events).toHaveBeenCalledTimes(1);

    clearSession();
    expect(getSession()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    setSession(session);
    expect(listener).toHaveBeenCalledTimes(2);
    window.removeEventListener(SESSION_STORAGE_EVENT_NAME, events);
  });

  it("returns a stable snapshot between writes", () => {
    setSession(session);
    expect(getSession()).toBe(getSession());
  });

  it("primes without notifying", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);
    primeSession(session);
    expect(getSession()).toEqual(session);
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });
});

describe("auth-session storage contract (R07-09)", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    clearSession();
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK;
    delete process.env.NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN;
    delete process.env.NEXT_PUBLIC_AUTH_LEGACY_SESSION_READ;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    clearSessionStorage();
  });

  it("writes memory only, never localStorage or sessionStorage", () => {
    writeSessionToStorage(session);

    expect(readSessionFromStorage()).toEqual(session);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("keeps a 0.6.x session signed in through the legacy localStorage read", () => {
    window.localStorage.setItem(
      LEGACY_SESSION_STORAGE_KEY,
      JSON.stringify({ ...session, refreshToken: "legacy-refresh" }),
    );

    const restored = readSessionFromStorage();

    expect(restored).toEqual(session);
    expect(getSession()).toEqual(session);
    // Removed only after a successful refresh or authenticated response.
    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).not.toBe(
      null,
    );
    discardLegacySessionStorage();
    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).toBeNull();
    expect(readSessionFromStorage()).toEqual(session);
  });

  it("ignores the legacy key when NEXT_PUBLIC_AUTH_LEGACY_SESSION_READ=false", () => {
    process.env.NEXT_PUBLIC_AUTH_LEGACY_SESSION_READ = "false";
    window.localStorage.setItem(
      LEGACY_SESSION_STORAGE_KEY,
      JSON.stringify(session),
    );

    expect(readSessionFromStorage()).toBeNull();
  });

  it.each([
    "not json",
    JSON.stringify({ userId: "", role: "member" }),
    JSON.stringify({ ...session, role: "superuser" }),
  ])("ignores an invalid legacy session %s", (raw) => {
    window.localStorage.setItem(LEGACY_SESSION_STORAGE_KEY, raw);
    expect(readSessionFromStorage()).toBeNull();
  });

  it("memory wins over the legacy key", () => {
    window.localStorage.setItem(
      LEGACY_SESSION_STORAGE_KEY,
      JSON.stringify({ ...session, accessToken: "legacy" }),
    );
    writeSessionToStorage(session);
    expect(readSessionFromStorage()?.accessToken).toBe("access-token-1");
  });

  it.each([
    ["NEXT_PUBLIC_AUTH_LOCAL_FALLBACK", "true"],
    ["NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN", "dev-token"],
  ])(
    "uses tab-scoped sessionStorage for the dev fallback (%s)",
    (name, value) => {
      process.env[name] = value;
      expect(isDevSessionPersistenceEnabled()).toBe(true);

      writeSessionToStorage({ ...session, refreshToken: "r" });
      expect(window.localStorage.length).toBe(0);
      const stored = JSON.parse(
        window.sessionStorage.getItem(DEV_SESSION_STORAGE_KEY) ?? "{}",
      ) as Record<string, unknown>;
      expect(stored.accessToken).toBe("access-token-1");
      expect(stored).not.toHaveProperty("refreshToken");

      // A reload starts with empty memory and reads the dev copy back.
      clearSession();
      expect(readSessionFromStorage()).toEqual(session);
    },
  );

  it("does not read sessionStorage outside the dev fallback", () => {
    expect(isDevSessionPersistenceEnabled()).toBe(false);
    window.sessionStorage.setItem(
      DEV_SESSION_STORAGE_KEY,
      JSON.stringify(session),
    );
    expect(readSessionFromStorage()).toBeNull();
  });

  it("clears memory, the legacy key and the dev key", () => {
    const events = vi.fn();
    window.addEventListener(SESSION_STORAGE_EVENT_NAME, events);
    writeSessionToStorage(session);
    window.localStorage.setItem(LEGACY_SESSION_STORAGE_KEY, "{}");
    window.sessionStorage.setItem(DEV_SESSION_STORAGE_KEY, "{}");

    clearSessionStorage();

    expect(getSession()).toBeNull();
    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(DEV_SESSION_STORAGE_KEY)).toBeNull();
    expect(events).toHaveBeenCalled();
    window.removeEventListener(SESSION_STORAGE_EVENT_NAME, events);
  });

  it("survives storage that throws", () => {
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    const removeItem = vi
      .spyOn(Storage.prototype, "removeItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK = "true";
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });

    expect(readSessionFromStorage()).toBeNull();
    expect(() => writeSessionToStorage(session)).not.toThrow();
    expect(getSession()).toEqual(session);
    expect(() => discardLegacySessionStorage()).not.toThrow();
    expect(() => clearSessionStorage()).not.toThrow();
    expect(getSession()).toBeNull();

    getItem.mockRestore();
    removeItem.mockRestore();
    setItem.mockRestore();
  });
});
