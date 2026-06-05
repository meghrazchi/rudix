import type { WizardStepProps } from "@/components/connectors/wizard/types";
import type { JiraWizardState } from "../JiraWizard.types";

const SCHEDULE_LABELS: Record<string, string> = {
  realtime: "Real-time (Webhooks)",
  hourly: "Hourly (Polling)",
  daily: "Daily at midnight",
  weekly: "Weekly (Weekends)",
};

type Row = { label: string; value: string };

export function JiraReviewStep({ state }: WizardStepProps<JiraWizardState>) {
  const host = state.siteUrl.replace(/^https?:\/\//, "");
  const projectsLabel =
    state.selectedProjectKeys.length === 0
      ? "All projects"
      : state.selectedProjectKeys.join(", ");

  const assets = ["Issues"];
  if (state.includeComments) assets.push("Comments");
  if (state.includeAttachments) assets.push("Attachments (OCR)");
  if (state.includeChangelog) assets.push("Changelog");

  const rows: Row[] = [
    { label: "Service", value: "Jira Cloud" },
    { label: "Site URL", value: host },
    { label: "Projects", value: projectsLabel },
    { label: "Included Assets", value: assets.join(", ") },
    { label: "Sync Schedule", value: SCHEDULE_LABELS[state.syncSchedule] ?? state.syncSchedule },
    {
      label: "Full Re-index",
      value: state.fullReindex ? "Every 30 days" : "Disabled",
    },
  ];

  const estimatedIssues = state.selectedProjectKeys.length === 0 ? "~7,500" : "~1,587";

  return (
    <div>
      <div className="text-center mb-8">
        <div className="w-20 h-20 bg-[#3525cd]/10 rounded-full flex items-center justify-center mx-auto mb-4">
          <span className="material-symbols-outlined text-[40px] text-[#3525cd]">
            verified_user
          </span>
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-[#1b1b24] mb-2">
          Ready to Connect
        </h2>
        <p className="text-base text-[#464555] max-w-md mx-auto">
          Review your settings before we initiate the first sync.
        </p>
      </div>

      <div className="space-y-0 mb-6">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex justify-between items-center py-3 border-b border-[#e4e1ee]"
          >
            <span className="text-sm text-[#464555]">{row.label}</span>
            <span className="text-sm font-semibold text-[#1b1b24] font-mono text-right max-w-[60%] truncate">
              {row.value}
            </span>
          </div>
        ))}
      </div>

      <div className="p-4 bg-[#e2dfff]/30 border border-[#3525cd]/20 rounded-lg flex items-start gap-4">
        <span className="material-symbols-outlined text-[#3525cd] shrink-0 mt-0.5">
          auto_awesome
        </span>
        <div>
          <h4 className="font-bold text-sm text-[#3525cd]">Initial Ingestion</h4>
          <p className="text-sm text-[#464555] mt-0.5">
            The first sync will process approximately {estimatedIssues} issues.
            Estimated completion: 8 minutes.
          </p>
        </div>
      </div>
    </div>
  );
}
