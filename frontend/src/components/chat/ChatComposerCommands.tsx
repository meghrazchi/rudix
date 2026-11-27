import { useTranslations } from "next-intl";

import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import type { AnswerLanguageMode } from "@/components/chat/chat-types";

/**
 * Additional composer settings popover (top-k, answer language, rerank and
 * agentic mode). The composer has no slash-command menu; these are the
 * composer's command controls.
 */
export function ChatComposerCommands({
  topK,
  minTopK,
  maxTopK,
  setTopK,
  answerLanguage,
  setAnswerLanguage,
  rerank,
  setRerank,
  agenticChatEnabled,
  agenticMode,
  setAgenticMode,
  hasConnectorScopeSelection,
}: {
  topK: number;
  minTopK: number;
  maxTopK: number;
  setTopK: (value: number) => void;
  answerLanguage: AnswerLanguageMode;
  setAnswerLanguage: (value: AnswerLanguageMode) => void;
  rerank: boolean;
  setRerank: (value: boolean) => void;
  agenticChatEnabled: boolean;
  agenticMode: boolean;
  setAgenticMode: (value: boolean) => void;
  hasConnectorScopeSelection: boolean;
}) {
  const t = useTranslations("chat.composer");
  const tLang = useTranslations("languageSwitcher");

  const answerLanguageOptions: ReadonlyArray<{
    value: AnswerLanguageMode;
    label: string;
  }> = [
    { value: "auto", label: t("answerAuto") },
    { value: "same_as_question", label: t("answerMatchQuestion") },
    { value: "en", label: tLang("en") },
    { value: "de", label: tLang("de") },
    { value: "es", label: tLang("es") },
    { value: "fr", label: tLang("fr") },
  ];

  return (
    <div className="absolute end-3 bottom-full z-30 mb-3 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-[#d7d4e8] bg-white p-3 shadow-2xl">
      <div className="mb-3">
        <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
          {t("additionalSettingsTitle")}
        </p>
        <p className="text-xs text-[#6a6780]">
          {t("additionalSettingsSubtitle")}
        </p>
      </div>
      <div className="flex flex-col gap-3">
        <div className="rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <label
              htmlFor="top-k-slider"
              className="text-[10px] font-bold tracking-widest text-[#464555] uppercase"
            >
              {t("topKLabel")}
            </label>
            <span className="font-mono text-xs text-[#3525cd]">{topK}</span>
          </div>
          <input
            id="top-k-slider"
            type="range"
            min={minTopK}
            max={maxTopK}
            value={topK}
            onChange={(event) => {
              const parsed = Number.parseInt(event.target.value, 10);
              if (Number.isFinite(parsed)) {
                setTopK(Math.min(maxTopK, Math.max(minTopK, parsed)));
              }
            }}
            className="h-1 w-full cursor-pointer appearance-none rounded-full bg-[#c7c4d8] accent-[#3525cd]"
          />
        </div>

        <div className="rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
          <div className="mb-2 flex items-center gap-2">
            <label
              htmlFor="answer-language"
              className="block text-[10px] font-bold tracking-widest text-[#464555] uppercase"
            >
              {t("answerLabel")}
            </label>
            <ContextualHelpLink topic="multilingual" />
          </div>
          <select
            id="answer-language"
            value={answerLanguage}
            onChange={(event) =>
              setAnswerLanguage(event.target.value as AnswerLanguageMode)
            }
            aria-label={t("answerLanguageAriaLabel")}
            className="w-full cursor-pointer rounded-lg border border-[#d2cee6] bg-white px-2 py-2 text-sm font-semibold text-[#3525cd] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
          >
            {answerLanguageOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-center justify-between rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
          <span>
            <span className="block text-[10px] font-bold tracking-widest text-[#464555] uppercase">
              {t("rerankLabel")}
            </span>
            <span className="block text-xs text-[#6a6780]">
              {t("rerankDescription")}
            </span>
          </span>
          <span className="relative inline-flex items-center">
            <input
              type="checkbox"
              checked={rerank}
              onChange={(event) => setRerank(event.target.checked)}
              className="peer sr-only"
            />
            <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd]" />
            <span className="absolute start-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5 rtl:peer-checked:-translate-x-3.5" />
          </span>
        </label>

        <label className="flex items-center justify-between rounded-xl border border-[#ece8f7] bg-[#faf9ff] p-3">
          <span>
            <span className="block text-[10px] font-bold tracking-widest text-[#464555] uppercase">
              {t("agenticLabel")}
            </span>
            <span className="block text-xs text-[#6a6780]">
              {agenticChatEnabled
                ? t("agenticDescription")
                : t("agenticDisabled")}
            </span>
          </span>
          <span className="relative inline-flex items-center">
            <input
              type="checkbox"
              checked={agenticMode}
              disabled={!agenticChatEnabled}
              onChange={(event) => setAgenticMode(event.target.checked)}
              className="peer sr-only"
            />
            <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd] peer-disabled:opacity-50" />
            <span className="absolute start-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5 peer-disabled:opacity-80 rtl:peer-checked:-translate-x-3.5" />
          </span>
        </label>
      </div>
      {agenticChatEnabled && hasConnectorScopeSelection ? (
        <p className="mt-3 text-xs text-[#8a4762]">
          {t("agenticConnectorWarning")}
        </p>
      ) : null}
    </div>
  );
}
