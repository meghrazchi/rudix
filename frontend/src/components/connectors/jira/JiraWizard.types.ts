export type SyncSchedule = "realtime" | "hourly" | "daily" | "weekly";

export type JiraWizardState = {
  siteUrl: string;
  authorized: boolean;
  selectedProjectKeys: string[];
  includeComments: boolean;
  includeAttachments: boolean;
  includeChangelog: boolean;
  syncSchedule: SyncSchedule;
  fullReindex: boolean;
};

export const JIRA_WIZARD_INITIAL_STATE: JiraWizardState = {
  siteUrl: "",
  authorized: false,
  selectedProjectKeys: [],
  includeComments: true,
  includeAttachments: false,
  includeChangelog: false,
  syncSchedule: "realtime",
  fullReindex: true,
};
