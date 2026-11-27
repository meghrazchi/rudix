import { useEffect, useMemo, useState } from "react";

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

export function readPersistedChatSettings(): PersistedChatSettings | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(CHAT_SETTINGS_STORAGE_KEY);
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

export function useChatSettings() {
  const persistedSettings = useMemo(() => readPersistedChatSettings(), []);
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

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const payload: PersistedChatSettings = {
      topK,
      rerank,
      agenticMode,
      answerLanguage,
    };
    window.localStorage.setItem(
      CHAT_SETTINGS_STORAGE_KEY,
      JSON.stringify(payload),
    );
  }, [agenticMode, answerLanguage, rerank, topK]);

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
