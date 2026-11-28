import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionStorage, writeSessionToStorage } from "@/lib/auth-session";

type Coordinator = typeof import("@/lib/auth-refresh-coordinator");

const LOCK_KEY = "rudix.auth.refresh.lock.v1";

async function loadTab(): Promise<Coordinator> {
  // A fresh module instance has its own actor id, like another browser tab.
  vi.resetModules();
  return import("@/lib/auth-refresh-coordinator");
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (error: unknown) => void = () => undefined;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("cross-tab refresh lease (R07-09)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    clearSessionStorage();
  });

  afterEach(() => {
    window.localStorage.clear();
    clearSessionStorage();
  });

  it("runs refreshes from two tabs one after the other, never overlapping", async () => {
    const tabA = await loadTab();
    const tabB = await loadTab();
    const timeline: string[] = [];
    let inFlight = 0;
    let maxInFlight = 0;
    const first = deferred<string>();

    function trackedRefresh(name: string, result: Promise<string>) {
      return async () => {
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        timeline.push(`${name}:start`);
        try {
          return await result;
        } finally {
          inFlight -= 1;
          timeline.push(`${name}:end`);
        }
      };
    }

    const refreshA = tabA.refreshWithCrossTabLease(
      null,
      trackedRefresh("A", first.promise),
    );
    await vi.waitFor(() => expect(timeline).toEqual(["A:start"]));

    const refreshB = tabB.refreshWithCrossTabLease(
      null,
      trackedRefresh("B", Promise.resolve("token-B")),
    );
    // B waits while A holds the lease; nothing is read from storage.
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(timeline).toEqual(["A:start"]);

    first.resolve("token-A");
    await expect(refreshA).resolves.toBe("token-A");
    await expect(refreshB).resolves.toBe("token-B");

    expect(timeline).toEqual(["A:start", "A:end", "B:start", "B:end"]);
    expect(maxInFlight).toBe(1);
    expect(window.localStorage.getItem(LOCK_KEY)).toBeNull();
  });

  it("the lease record never carries a token", async () => {
    const tab = await loadTab();
    const baseline = {
      userId: "u",
      email: null,
      role: "member" as const,
      organizationId: null,
      organizationName: null,
      accessToken: "secret-token",
    };
    writeSessionToStorage(baseline);
    const setItem = vi.spyOn(Storage.prototype, "setItem");

    await tab.refreshWithCrossTabLease(baseline, async () => "done");

    for (const [key, value] of setItem.mock.calls) {
      expect(key).toBe(LOCK_KEY);
      expect(String(value)).not.toContain("secret-token");
      expect(Object.keys(JSON.parse(String(value))).sort()).toEqual([
        "acquiredAt",
        "expiresAt",
        "leaseId",
        "ownerId",
      ]);
    }
    expect(setItem).toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("returns this tab's session when it changed while waiting", async () => {
    const tabA = await loadTab();
    const tabB = await loadTab();
    const holder = deferred<string>();
    const refreshA = tabA.refreshWithCrossTabLease(null, () => holder.promise);
    await vi.waitFor(() =>
      expect(window.localStorage.getItem(LOCK_KEY)).not.toBeNull(),
    );
    await new Promise((resolve) => setTimeout(resolve, 40));

    const refreshB = vi.fn(async () => "should-not-run");
    const waiting = tabB.refreshWithCrossTabLease(null, refreshB);
    writeSessionToStorage({
      userId: "user-1",
      email: null,
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: "same-tab-token",
    });

    await expect(waiting).resolves.toMatchObject({
      accessToken: "same-tab-token",
    });
    expect(refreshB).not.toHaveBeenCalled();
    holder.resolve("A");
    await refreshA;
  });

  it("takes over an expired lease left by a closed tab", async () => {
    window.localStorage.setItem(
      LOCK_KEY,
      JSON.stringify({
        ownerId: "closed-tab",
        leaseId: "l",
        acquiredAt: Date.now() - 20_000,
        expiresAt: Date.now() - 5_000,
      }),
    );
    const tab = await loadTab();
    await expect(
      tab.refreshWithCrossTabLease(null, async () => "fresh"),
    ).resolves.toBe("fresh");
  });

  it("releases the lease when the refresh fails", async () => {
    const tab = await loadTab();
    await expect(
      tab.refreshWithCrossTabLease(null, async () => {
        throw new Error("401");
      }),
    ).rejects.toThrow("401");
    expect(window.localStorage.getItem(LOCK_KEY)).toBeNull();
  });

  it("wakes a waiting tab on a storage event for the lease", async () => {
    window.localStorage.setItem(
      LOCK_KEY,
      JSON.stringify({
        ownerId: "other-tab",
        leaseId: "l",
        acquiredAt: Date.now(),
        expiresAt: Date.now() + 10_000,
      }),
    );
    const tab = await loadTab();
    const refresh = vi.fn(async () => "after-release");
    const result = tab.refreshWithCrossTabLease(null, refresh);

    window.localStorage.removeItem(LOCK_KEY);
    window.dispatchEvent(
      new StorageEvent("storage", { key: LOCK_KEY, newValue: null }),
    );

    await expect(result).resolves.toBe("after-release");
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
