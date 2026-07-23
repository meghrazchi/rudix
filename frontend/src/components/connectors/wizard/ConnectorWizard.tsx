"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { ConnectorWizardConfig } from "./types";

type Props<TState extends Record<string, unknown>> = {
  config: ConnectorWizardConfig<TState>;
};

export function ConnectorWizard<TState extends Record<string, unknown>>({
  config,
}: Props<TState>) {
  const t = useTranslations("connectors.setup.wizard");
  const { steps, initialState, onComplete, onCancel } = config;
  const [current, setCurrent] = useState(0);
  const [state, setState] = useState<TState>(initialState);
  const [completing, setCompleting] = useState(false);

  const total = steps.length;
  const step = steps[current]!;
  const StepComponent = step.component;

  function onChange(patch: Partial<TState>) {
    setState((prev) => ({ ...prev, ...patch }));
  }

  function goNext() {
    if (current < total - 1) setCurrent((c) => c + 1);
  }

  function goPrev() {
    if (current > 0) setCurrent((c) => c - 1);
  }

  async function handleComplete() {
    setCompleting(true);
    try {
      await onComplete(state);
    } finally {
      setCompleting(false);
    }
  }

  const canProceed = step.canProceed ? step.canProceed(state) : true;
  const isLast = current === total - 1;
  const progressPct = total > 1 ? (current / (total - 1)) * 100 : 0;

  return (
    <div className="w-full max-w-4xl overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
      {/* Stepper header */}
      <div className="border-b border-[#c7c4d8] bg-[#f5f2ff] px-8 py-5">
        <div className="relative flex items-center justify-between">
          {/* Background track */}
          <div className="absolute top-5 left-0 h-0.5 w-full bg-[#c7c4d8]" />
          {/* Progress fill */}
          <div
            className="absolute top-5 left-0 h-0.5 bg-[#3525cd] transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />

          {steps.map((s, i) => {
            const done = i < current;
            const active = i === current;
            return (
              <div
                key={s.key}
                className="relative z-10 flex flex-col items-center gap-2"
              >
                <div
                  className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold transition-colors ${
                    done
                      ? "bg-[#e2dfff] text-[#3525cd]"
                      : active
                        ? "bg-[#3525cd] text-white"
                        : "bg-[#e4e1ee] text-[#464555]"
                  }`}
                >
                  {done ? (
                    <span className="material-symbols-outlined text-sm">
                      check
                    </span>
                  ) : (
                    i + 1
                  )}
                </div>
                <span
                  className={`text-[10px] font-semibold tracking-wide uppercase ${
                    active ? "text-[#3525cd]" : "text-[#464555]"
                  }`}
                >
                  {s.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Step content */}
      <div className="min-h-[420px] p-8">
        <StepComponent state={state} onChange={onChange} onNext={goNext} />
      </div>

      {/* Footer actions */}
      <div className="flex items-center justify-between border-t border-[#c7c4d8] bg-[#f0ecf9] px-8 py-4">
        <button
          type="button"
          onClick={goPrev}
          disabled={current === 0}
          className="rounded-lg border border-[#777587] px-6 py-2.5 font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-30"
        >
          {t("back")}
        </button>

        <div className="flex items-center gap-4">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2.5 font-semibold text-[#464555] hover:underline"
            >
              {t("cancel")}
            </button>
          )}

          {isLast ? (
            <button
              type="button"
              onClick={handleComplete}
              disabled={!canProceed || completing}
              className="rounded-lg bg-[#3525cd] px-8 py-2.5 font-bold text-white transition-all hover:opacity-90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {completing ? t("connecting") : t("complete")}
            </button>
          ) : (
            <button
              type="button"
              onClick={goNext}
              disabled={!canProceed}
              className="rounded-lg bg-[#3525cd] px-8 py-2.5 font-bold text-white transition-all hover:opacity-90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("next")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
