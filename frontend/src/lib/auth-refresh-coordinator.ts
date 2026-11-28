import {
  readSessionFromStorage,
  SESSION_STORAGE_EVENT_NAME,
  type AuthenticatedSession,
} from "@/lib/auth-session";

const REFRESH_LOCK_KEY = "rudix.auth.refresh.lock.v1";
const REFRESH_LOCK_TTL_MS = 15_000;
const REFRESH_LOCK_SETTLE_MS = 25;
const REFRESH_LOCK_POLL_MS = 50;
const REFRESH_ACTOR_ID = generateId();

type RefreshLockRecord = {
  ownerId: string;
  leaseId: string;
  acquiredAt: number;
  expiresAt: number;
};

function generateId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getRefreshActorId(): string {
  return REFRESH_ACTOR_ID;
}

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function getSessionFingerprint(
  session: AuthenticatedSession | null,
): string | null {
  if (!session) {
    return null;
  }

  return `${session.userId}:${trimToNull(session.accessToken) ?? ""}`;
}

function readLockRecord(): RefreshLockRecord | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(REFRESH_LOCK_KEY);
    if (!raw) {
      return null;
    }

    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      return null;
    }

    const candidate = parsed as Partial<RefreshLockRecord>;
    if (
      typeof candidate.ownerId !== "string" ||
      typeof candidate.leaseId !== "string" ||
      typeof candidate.acquiredAt !== "number" ||
      typeof candidate.expiresAt !== "number"
    ) {
      return null;
    }

    return {
      ownerId: candidate.ownerId,
      leaseId: candidate.leaseId,
      acquiredAt: candidate.acquiredAt,
      expiresAt: candidate.expiresAt,
    };
  } catch {
    return null;
  }
}

function writeLockRecord(record: RefreshLockRecord): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(REFRESH_LOCK_KEY, JSON.stringify(record));
}

function clearLockRecordIfOwned(record: RefreshLockRecord): void {
  const current = readLockRecord();
  if (
    current &&
    current.ownerId === record.ownerId &&
    current.leaseId === record.leaseId
  ) {
    window.localStorage.removeItem(REFRESH_LOCK_KEY);
  }
}

export function clearCrossTabRefreshLease(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(REFRESH_LOCK_KEY);
}

function isExpired(record: RefreshLockRecord): boolean {
  return record.expiresAt <= Date.now();
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function tryAcquireLock(): RefreshLockRecord | null {
  if (typeof window === "undefined") {
    return null;
  }

  const ownerId = getRefreshActorId();
  const leaseId = generateId();
  const now = Date.now();
  const candidate: RefreshLockRecord = {
    ownerId,
    leaseId,
    acquiredAt: now,
    expiresAt: now + REFRESH_LOCK_TTL_MS,
  };

  const current = readLockRecord();
  if (current && !isExpired(current) && current.ownerId !== ownerId) {
    return null;
  }

  writeLockRecord(candidate);

  const stored = readLockRecord();
  if (
    stored?.ownerId !== candidate.ownerId ||
    stored.leaseId !== candidate.leaseId
  ) {
    return null;
  }

  return candidate;
}

function isRefreshSessionChanged(baselineFingerprint: string | null): boolean {
  return (
    getSessionFingerprint(readSessionFromStorage()) !== baselineFingerprint
  );
}

function isLeaseHeldByAnotherActor(): boolean {
  const current = readLockRecord();
  return (
    current !== null &&
    !isExpired(current) &&
    current.ownerId !== getRefreshActorId()
  );
}

/**
 * Waits until no other tab holds the lease (released or expired), or until
 * this tab's own in-memory session changed. The lease record carries no
 * token, and a waiting tab never reads a token from storage (R07-09).
 */
async function waitForLeaseRelease(
  baselineFingerprint: string | null,
): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  await new Promise<void>((resolve) => {
    let resolved = false;
    const intervalId = window.setInterval(check, REFRESH_LOCK_POLL_MS);
    const timeoutId = window.setTimeout(finish, REFRESH_LOCK_TTL_MS + 500);

    function finish(): void {
      if (resolved) {
        return;
      }
      resolved = true;
      window.clearInterval(intervalId);
      window.clearTimeout(timeoutId);
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(SESSION_STORAGE_EVENT_NAME, check);
      resolve();
    }

    function check(): void {
      if (
        !isLeaseHeldByAnotherActor() ||
        isRefreshSessionChanged(baselineFingerprint)
      ) {
        finish();
      }
    }

    function onStorage(event: StorageEvent): void {
      if (event.key === REFRESH_LOCK_KEY || event.key === null) {
        check();
      }
    }

    window.addEventListener("storage", onStorage);
    window.addEventListener(SESSION_STORAGE_EVENT_NAME, check);
    check();
  });
}

/**
 * Runs `refresh` while holding the cross-tab lease, so refresh requests from
 * different tabs never overlap. A rotated refresh token presented twice
 * revokes every session of the user, so a tab that waited never reuses a
 * token: once the holder releases, it takes the lease and runs its own
 * refresh with the cookie the holder already rotated. Only when this tab's
 * own in-memory session changed meanwhile (another caller in the same tab
 * refreshed) does it return that session instead.
 */
export async function refreshWithCrossTabLease<T>(
  baselineSession: AuthenticatedSession | null,
  refresh: () => Promise<T>,
): Promise<T> {
  const baselineFingerprint = getSessionFingerprint(baselineSession);

  while (true) {
    if (isRefreshSessionChanged(baselineFingerprint)) {
      return readSessionFromStorage() as T;
    }

    const lease = tryAcquireLock();
    if (lease) {
      try {
        await delay(REFRESH_LOCK_SETTLE_MS);
        const currentLease = readLockRecord();
        if (
          currentLease?.ownerId !== lease.ownerId ||
          currentLease.leaseId !== lease.leaseId
        ) {
          continue;
        }

        return await refresh();
      } finally {
        clearLockRecordIfOwned(lease);
      }
    }

    await waitForLeaseRelease(baselineFingerprint);
  }
}
