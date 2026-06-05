"use client";

import { ConnectorWizard } from "@/components/connectors/wizard/ConnectorWizard";
import type { ConnectorWizardConfig } from "@/components/connectors/wizard/types";
import { JIRA_WIZARD_INITIAL_STATE, type JiraWizardState } from "./JiraWizard.types";
import { JiraIntroStep } from "./steps/JiraIntroStep";
import { JiraAuthStep } from "./steps/JiraAuthStep";
import { JiraProjectsStep } from "./steps/JiraProjectsStep";
import { JiraContentStep } from "./steps/JiraContentStep";
import { JiraSyncStep } from "./steps/JiraSyncStep";
import { JiraReviewStep } from "./steps/JiraReviewStep";

const JIRA_WIZARD_CONFIG: Omit<ConnectorWizardConfig<JiraWizardState>, "onComplete" | "onCancel"> = {
  providerKey: "jira",
  displayName: "Jira",
  initialState: JIRA_WIZARD_INITIAL_STATE,
  steps: [
    {
      key: "intro",
      label: "Intro",
      component: JiraIntroStep,
    },
    {
      key: "auth",
      label: "Auth",
      component: JiraAuthStep,
      canProceed: (s) => s.authorized,
    },
    {
      key: "projects",
      label: "Projects",
      component: JiraProjectsStep,
      canProceed: (s) => s.selectedProjectKeys.length > 0,
    },
    {
      key: "content",
      label: "Content",
      component: JiraContentStep,
    },
    {
      key: "sync",
      label: "Sync",
      component: JiraSyncStep,
    },
    {
      key: "review",
      label: "Review",
      component: JiraReviewStep,
    },
  ],
};

type Props = {
  onComplete?: (state: JiraWizardState) => void | Promise<void>;
  onCancel?: () => void;
};

export function JiraWizard({ onComplete, onCancel }: Props) {
  const config: ConnectorWizardConfig<JiraWizardState> = {
    ...JIRA_WIZARD_CONFIG,
    onComplete: onComplete ?? (() => {}),
    onCancel,
  };
  return <ConnectorWizard config={config} />;
}
