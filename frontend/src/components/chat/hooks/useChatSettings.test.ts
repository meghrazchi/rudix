import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  chatSettingsStorageKey,
  readPersistedChatSettings,
  removeLegacyChatSettings,
  useChatSettings,
  type ChatSettingsIdentity,
} from "@/components/chat/hooks/useChatSettings";

const LEGACY_KEY = "rudix.chat.settings.v1";
const ALICE_KEY = "rudix.chat.settings.v1:org-1:alice";

function stored(key: string) {
  const raw = window.localStorage.getItem(key);
  return raw ? JSON.parse(raw) : null;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chat settings storage key (R05-13)", () => {
  it("namespaces by organisation and user", () => {
    expect(chatSettingsStorageKey("org-1", "alice")).toBe(ALICE_KEY);
    expect(chatSettingsStorageKey(null, "alice")).toBeNull();
    expect(chatSettingsStorageKey("org-1", undefined)).toBeNull();
    expect(readPersistedChatSettings(null)).toBeNull();
  });

  it("ignores and deletes the legacy global key on first read", () => {
    window.localStorage.setItem(
      LEGACY_KEY,
      JSON.stringify({ topK: 9, rerank: false, agenticMode: true }),
    );
    const { result } = renderHook(() =>
      useChatSettings({ organizationId: "org-1", userId: "alice" }),
    );
    expect(window.localStorage.getItem(LEGACY_KEY)).toBeNull();
    expect(result.current.topK).toBe(5);
    expect(result.current.rerank).toBe(true);
    expect(result.current.agenticMode).toBe(false);
  });

  it("reads and writes only the namespaced key", () => {
    window.localStorage.setItem(
      ALICE_KEY,
      JSON.stringify({ topK: 7, rerank: false, answerLanguage: "de" }),
    );
    const { result } = renderHook(() =>
      useChatSettings({ organizationId: "org-1", userId: "alice" }),
    );
    expect(result.current.topK).toBe(7);
    expect(result.current.rerank).toBe(false);
    expect(result.current.answerLanguage).toBe("de");
    act(() => result.current.setTopK(3));
    expect(stored(ALICE_KEY)).toMatchObject({ topK: 3, rerank: false });
    expect(window.localStorage.getItem(LEGACY_KEY)).toBeNull();
  });

  it("keeps two users of the same browser apart", () => {
    const { result, rerender } = renderHook(
      (identity: ChatSettingsIdentity) => useChatSettings(identity),
      { initialProps: { organizationId: "org-1", userId: "alice" } },
    );
    act(() => result.current.setTopK(11));
    expect(stored(ALICE_KEY)).toMatchObject({ topK: 11 });

    rerender({ organizationId: "org-1", userId: "bob" });
    expect(result.current.topK).toBe(5);
    act(() => result.current.setRerank(false));
    expect(stored("rudix.chat.settings.v1:org-1:bob")).toMatchObject({
      topK: 5,
      rerank: false,
    });
    expect(stored(ALICE_KEY)).toMatchObject({ topK: 11, rerank: true });

    rerender({ organizationId: "org-1", userId: "alice" });
    expect(result.current.topK).toBe(11);
  });

  it("loads the identity's settings once the session arrives, writing nothing before", () => {
    window.localStorage.setItem(
      ALICE_KEY,
      JSON.stringify({ topK: 8, agenticMode: true }),
    );
    const { result, rerender } = renderHook(
      (identity: ChatSettingsIdentity) => useChatSettings(identity),
      {
        initialProps: {
          organizationId: null,
          userId: null,
        } as ChatSettingsIdentity,
      },
    );
    expect(result.current.topK).toBe(5);
    expect(window.localStorage.length).toBe(1);

    rerender({ organizationId: "org-1", userId: "alice" });
    expect(result.current.topK).toBe(8);
    expect(result.current.agenticMode).toBe(true);
    expect(stored(ALICE_KEY)).toMatchObject({ topK: 8, agenticMode: true });
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => removeLegacyChatSettings()).not.toThrow();
    const { result } = renderHook(() =>
      useChatSettings({ organizationId: "org-1", userId: "alice" }),
    );
    expect(() => act(() => result.current.setTopK(4))).not.toThrow();
    expect(result.current.topK).toBe(4);
  });

  it("works without an identity argument", () => {
    const { result } = renderHook(() => useChatSettings());
    expect(result.current.topK).toBe(5);
    expect(window.localStorage.length).toBe(0);
  });
});
