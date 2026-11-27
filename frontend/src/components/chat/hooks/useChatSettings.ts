import { useEffect, useState } from "react";

import {
  CHAT_SETTINGS_STORAGE_KEY,
  DEFAULT_AGENTIC_MODE,
  DEFAULT_TOP_K,
  MAX_TOP_K,
  MIN_TOP_K,
  type AnswerLanguageMode,
  type ChatScopeMode,
} from "@/components/chat/chat-types";

export type PersistedChatSettings = {
  topK: number;
  rerank: boolean;
  selectedDocumentIds?: string[];
  agenticMode?: boolean;
  scopeMode?: ChatScopeMode;
  selectedCollectionIds?: string[];
  selectedConnectorConnectionIds?: string[];
  selectedProviderSourceIds?: string[];
  answerLanguage?: AnswerLanguageMode;
};

export type ChatSettingsIdentity = {
  organizationId: string | null;
  userId: string | null;
};

/**
 * `rudix.chat.settings.v1:<organizationId>:<userId>` (R05-13). Settings are
 * per organisation and user, so two people sharing a browser, or one person in
 * two organisations, never read each other's choices. Null without an identity.
 */
export function chatSettingsStorageKey(
  organizationId: string | null | undefined,
  userId: string | null | undefined,
): string | null {
  if (!organizationId || !userId) return null;
  return `${CHAT_SETTINGS_STORAGE_KEY}:${organizationId}:${userId}`;
}

/**
 * The pre-0.5.0 key was global per browser and may belong to another user,
 * so it is never read; it is deleted the first time settings are read.
 */
export function removeLegacyChatSettings(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(CHAT_SETTINGS_STORAGE_KEY);
  } catch {
    // Storage blocked: nothing to clean up.
  }
}

export function readPersistedChatSettings(
  storageKey: string | null,
): PersistedChatSettings | null {
  if (typeof window === "undefined" || !storageKey) {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedChatSettings> | null;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }

    const storedTopK =
      typeof parsed.topK === "number" && Number.isFinite(parsed.topK)
        ? Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, Math.trunc(parsed.topK)))
        : DEFAULT_TOP_K;

    const validLanguageModes: AnswerLanguageMode[] = [
      "auto",
      "same_as_question",
      "en",
      "de",
      "es",
      "fr",
    ];
    const answerLanguage: AnswerLanguageMode = validLanguageModes.includes(
      parsed.answerLanguage as AnswerLanguageMode,
    )
      ? (parsed.answerLanguage as AnswerLanguageMode)
      : "auto";

    return {
      topK: storedTopK,
      rerank: parsed.rerank !== false,
      selectedDocumentIds: [],
      agenticMode: parsed.agenticMode === true,
      scopeMode: "all",
      selectedCollectionIds: [],
      selectedConnectorConnectionIds: [],
      selectedProviderSourceIds: [],
      answerLanguage,
    };
  } catch {
    return null;
  }
}

export function useChatSettings(
  identity: ChatSettingsIdentity = { organizationId: null, userId: null },
) {
  const storageKey = chatSettingsStorageKey(
    identity.organizationId,
    identity.userId,
  );
  const [initial] = useState(() => {
    removeLegacyChatSettings();
    return {
      key: storageKey,
      settings: readPersistedChatSettings(storageKey),
    };
  });
  const persistedSettings = initial.settings;
  const [loadedKey, setLoadedKey] = useState<string | null>(initial.key);
  const [answerLanguage, setAnswerLanguage] = useState<AnswerLanguageMode>(
    () => persistedSettings?.answerLanguage ?? "auto",
  );
  const [topK, setTopK] = useState(
    () => persistedSettings?.topK ?? DEFAULT_TOP_K,
  );
  const [rerank, setRerank] = useState(() => persistedSettings?.rerank ?? true);
  const [agenticMode, setAgenticMode] = useState(
    () => persistedSettings?.agenticMode === true || DEFAULT_AGENTIC_MODE,
  );

  // The identity arrives after the first render (or changes with the
  // organisation): load that identity's settings before anything is written.
  if (storageKey !== loadedKey) {
    const next = readPersistedChatSettings(storageKey);
    setLoadedKey(storageKey);
    setAnswerLanguage(next?.answerLanguage ?? "auto");
    setTopK(next?.topK ?? DEFAULT_TOP_K);
    setRerank(next?.rerank ?? true);
    setAgenticMode(next?.agenticMode === true || DEFAULT_AGENTIC_MODE);
  }

  useEffect(() => {
    if (typeof window === "undefined" || !storageKey) {
      return;
    }
    if (storageKey !== loadedKey) {
      return;
    }
    const payload: PersistedChatSettings = {
      topK,
      rerank,
      agenticMode,
      answerLanguage,
    };
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    } catch {
      // Storage full or blocked: settings stay for this page only.
    }
  }, [agenticMode, answerLanguage, loadedKey, rerank, storageKey, topK]);

  return {
    persistedSettings,
    answerLanguage,
    setAnswerLanguage,
    topK,
    setTopK,
    rerank,
    setRerank,
    agenticMode,
    setAgenticMode,
  };
}

export type ChatSettingsController = ReturnType<typeof useChatSettings>;
