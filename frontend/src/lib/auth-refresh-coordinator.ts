import {
  readSessionFromStorage,
  SESSION_STORAGE_EVENT_NAME,
  SESSION_STORAGE_KEY,
  type AuthenticatedSession,
} from "@/lib/auth-session";

const REFRESH_LOCK_KEY = "rudix.auth.refresh.lock.v1";
const REFRESH_LOCK_TTL_MS = 15_000;
const REFRESH_LOCK_SETTLE_MS = 25;
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

function tryAcquireLock(
  sessionFingerprint: string | null,
): RefreshLockRecord | null {
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

  const currentSessionFingerprint = getSessionFingerprint(
    readSessionFromStorage(),
  );
  if (
    currentSessionFingerprint !== sessionFingerprint &&
    sessionFingerprint !== null
  ) {
    clearLockRecordIfOwned(candidate);
    return null;
  }

  return candidate;
}

function isRefreshSessionChanged(baselineFingerprint: string | null): boolean {
  return (
    getSessionFingerprint(readSessionFromStorage()) !== baselineFingerprint
  );
}

async function waitForSessionUpdate(
  baselineFingerprint: string | null,
): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }

  if (isRefreshSessionChanged(baselineFingerprint)) {
    return true;
  }

  return new Promise<boolean>((resolve) => {
    let resolved = false;
    const timeoutId = window.setTimeout(() => {
      cleanup();
      resolve(isRefreshSessionChanged(baselineFingerprint));
    }, REFRESH_LOCK_TTL_MS + 500);

    function cleanup(): void {
      if (resolved) {
        return;
      }
      resolved = true;
      window.clearTimeout(timeoutId);
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(
        SESSION_STORAGE_EVENT_NAME,
        onSessionStorageEvent as EventListener,
      );
    }

    function finish(): void {
      if (resolved) {
        return;
      }
      if (isRefreshSessionChanged(baselineFingerprint)) {
        cleanup();
        resolve(true);
      }
    }

    function onStorage(event: StorageEvent): void {
      if (event.key !== SESSION_STORAGE_KEY) {
        return;
      }
      finish();
    }

    function onSessionStorageEvent(): void {
      finish();
    }

    window.addEventListener("storage", onStorage);
    window.addEventListener(
      SESSION_STORAGE_EVENT_NAME,
      onSessionStorageEvent as EventListener,
    );
  });
}

export async function refreshWithCrossTabLease<T>(
  baselineSession: AuthenticatedSession | null,
  refresh: () => Promise<T>,
): Promise<T> {
  const baselineFingerprint = getSessionFingerprint(baselineSession);

  while (true) {
    const lease = tryAcquireLock(baselineFingerprint);
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

    const sessionChanged = await waitForSessionUpdate(baselineFingerprint);
    if (sessionChanged) {
      return readSessionFromStorage() as T;
    }
  }
}
