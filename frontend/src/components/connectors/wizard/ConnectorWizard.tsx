"use client";

import { useState } from "react";
import type { ConnectorWizardConfig } from "./types";

type Props<TState extends Record<string, unknown>> = {
  config: ConnectorWizardConfig<TState>;
};

export function ConnectorWizard<TState extends Record<string, unknown>>({
  config,
}: Props<TState>) {
  const { steps, initialState, onComplete, onCancel, displayName } = config;
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
    <div className="w-full max-w-4xl bg-white rounded-xl border border-[#c7c4d8] overflow-hidden shadow-sm">
      {/* Stepper header */}
      <div className="bg-[#f5f2ff] border-b border-[#c7c4d8] px-8 py-5">
        <div className="relative flex items-center justify-between">
          {/* Background track */}
          <div className="absolute top-5 left-0 w-full h-0.5 bg-[#c7c4d8]" />
          {/* Progress fill */}
          <div
            className="absolute top-5 left-0 h-0.5 bg-[#3525cd] transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />

          {steps.map((s, i) => {
            const done = i < current;
            const active = i === current;
            return (
              <div key={s.key} className="relative z-10 flex flex-col items-center gap-2">
                <div
                  className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                    done
                      ? "bg-[#e2dfff] text-[#3525cd]"
                      : active
                        ? "bg-[#3525cd] text-white"
                        : "bg-[#e4e1ee] text-[#464555]"
                  }`}
                >
                  {done ? (
                    <span className="material-symbols-outlined text-sm">check</span>
                  ) : (
                    i + 1
                  )}
                </div>
                <span
                  className={`text-[10px] font-semibold uppercase tracking-wide ${
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
      <div className="p-8 min-h-[420px]">
        <StepComponent state={state} onChange={onChange} onNext={goNext} />
      </div>

      {/* Footer actions */}
      <div className="bg-[#f0ecf9] border-t border-[#c7c4d8] px-8 py-4 flex items-center justify-between">
        <button
          type="button"
          onClick={goPrev}
          disabled={current === 0}
          className="px-6 py-2.5 rounded-lg border border-[#777587] text-[#464555] font-semibold hover:bg-[#eae6f4] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Back
        </button>

        <div className="flex items-center gap-4">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2.5 text-[#464555] font-semibold hover:underline"
            >
              Cancel
            </button>
          )}

          {isLast ? (
            <button
              type="button"
              onClick={handleComplete}
              disabled={!canProceed || completing}
              className="px-8 py-2.5 bg-[#3525cd] text-white rounded-lg font-bold hover:opacity-90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {completing ? "Connecting…" : `Complete Connection`}
            </button>
          ) : (
            <button
              type="button"
              onClick={goNext}
              disabled={!canProceed}
              className="px-8 py-2.5 bg-[#3525cd] text-white rounded-lg font-bold hover:opacity-90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
