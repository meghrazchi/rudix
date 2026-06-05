import type { ComponentType } from "react";

export type WizardStepProps<TState> = {
  state: TState;
  onChange: (patch: Partial<TState>) => void;
  /** Call to programmatically advance (e.g. after OAuth redirect completes). */
  onNext: () => void;
};

export type WizardStep<TState> = {
  key: string;
  /** Short label shown under stepper circle. */
  label: string;
  component: ComponentType<WizardStepProps<TState>>;
  /** Return false to disable the Next button; defaults to true. */
  canProceed?: (state: TState) => boolean;
};

export type ConnectorWizardConfig<TState extends Record<string, unknown>> = {
  providerKey: string;
  displayName: string;
  initialState: TState;
  steps: WizardStep<TState>[];
  onComplete: (state: TState) => void | Promise<void>;
  onCancel?: () => void;
};
