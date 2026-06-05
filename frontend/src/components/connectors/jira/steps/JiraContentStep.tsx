import type { WizardStepProps } from "@/components/connectors/wizard/types";
import type { JiraWizardState } from "../JiraWizard.types";

type ContentOption = {
  key: keyof Pick<
    JiraWizardState,
    "includeComments" | "includeAttachments" | "includeChangelog"
  >;
  icon: string;
  title: string;
  description: string;
  alwaysOn?: boolean;
};

const OPTIONS: ContentOption[] = [
  {
    key: "includeComments",
    icon: "subject",
    title: "Issue Summaries & Descriptions",
    description: "Essential core data — always included for indexing.",
    alwaysOn: true,
  },
  {
    key: "includeComments",
    icon: "chat",
    title: "Comments & Discussions",
    description: "Include all thread history for richer context.",
  },
  {
    key: "includeAttachments",
    icon: "attachment",
    title: "Attachments (OCR enabled)",
    description: "Scan PDFs, images, and documents attached to issues.",
  },
  {
    key: "includeChangelog",
    icon: "history",
    title: "Changelog & Status Updates",
    description: "Track state transitions and assignment history.",
  },
];

export function JiraContentStep({ state, onChange }: WizardStepProps<JiraWizardState>) {
  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-[#1b1b24] mb-1">
        Content Extraction Rules
      </h2>
      <p className="text-base text-[#464555] mb-8">
        Define exactly what parts of each issue Rudix should ingest.
      </p>

      <div className="space-y-3">
        {OPTIONS.map((option) => {
          const checked = option.alwaysOn ? true : !!state[option.key];
          return (
            <label
              key={`${option.key}-${option.icon}`}
              className={`flex items-center justify-between p-5 rounded-xl border transition-colors ${
                option.alwaysOn
                  ? "bg-[#f5f2ff] border-[#c7c4d8] cursor-default"
                  : "border-[#c7c4d8] hover:bg-[#f5f2ff] cursor-pointer"
              }`}
            >
              <div className="flex items-center gap-5">
                <div className="p-2 bg-[#3525cd]/10 rounded-lg text-[#3525cd]">
                  <span className="material-symbols-outlined text-[22px]">
                    {option.icon}
                  </span>
                </div>
                <div>
                  <div className="font-semibold text-sm text-[#1b1b24]">
                    {option.title}
                    {option.alwaysOn && (
                      <span className="ml-2 text-xs font-normal text-[#777587]">
                        (required)
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-[#464555] mt-0.5">
                    {option.description}
                  </div>
                </div>
              </div>

              <input
                type="checkbox"
                checked={checked}
                disabled={option.alwaysOn}
                onChange={() =>
                  !option.alwaysOn &&
                  onChange({ [option.key]: !state[option.key] } as Partial<JiraWizardState>)
                }
                className="w-6 h-6 rounded border-[#c7c4d8] text-[#3525cd] focus:ring-[#3525cd] disabled:opacity-60"
              />
            </label>
          );
        })}
      </div>
    </div>
  );
}
