import type { WizardStepProps } from "@/components/connectors/wizard/types";
import type { JiraWizardState } from "../JiraWizard.types";

export function JiraIntroStep(_: WizardStepProps<JiraWizardState>) {
  return (
    <div>
      <div className="flex flex-col md:flex-row gap-6 items-center mb-8">
        <div className="flex-1">
          <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24] mb-4">
            Connect your Jira Workspace
          </h1>
          <p className="text-base text-[#464555] leading-relaxed">
            Unlock powerful RAG capabilities by indexing your Jira project data.
            Rudix securely connects to your Atlassian instance to transform
            tickets, comments, and attachments into actionable knowledge for your
            AI agents.
          </p>
        </div>

        <div className="w-full md:w-56 aspect-square bg-[#3525cd]/5 rounded-2xl flex items-center justify-center border border-[#3525cd]/20 relative overflow-hidden shrink-0">
          <span className="material-symbols-outlined text-[80px] text-[#3525cd]">hub</span>
          <div className="absolute inset-0 bg-gradient-to-tr from-[#3525cd]/10 to-transparent" />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="p-4 bg-[#f5f2ff] rounded-lg border border-[#c7c4d8]">
          <div className="flex items-center gap-2 mb-2 text-[#3525cd]">
            <span className="material-symbols-outlined text-[20px]">description</span>
            <h4 className="font-bold text-sm">Issue Metadata</h4>
          </div>
          <p className="text-sm text-[#464555]">
            Import titles, descriptions, and custom fields to maintain full
            context of every task.
          </p>
        </div>

        <div className="p-4 bg-[#f5f2ff] rounded-lg border border-[#c7c4d8]">
          <div className="flex items-center gap-2 mb-2 text-[#3525cd]">
            <span className="material-symbols-outlined text-[20px]">forum</span>
            <h4 className="font-bold text-sm">Team Discussions</h4>
          </div>
          <p className="text-sm text-[#464555]">
            Capture threaded comments and decision histories for deeper
            situational awareness.
          </p>
        </div>

        <div className="p-4 bg-[#f5f2ff] rounded-lg border border-[#c7c4d8]">
          <div className="flex items-center gap-2 mb-2 text-[#3525cd]">
            <span className="material-symbols-outlined text-[20px]">attachment</span>
            <h4 className="font-bold text-sm">Attachments</h4>
          </div>
          <p className="text-sm text-[#464555]">
            Scan PDFs, images, and documents attached to issues via OCR
            extraction.
          </p>
        </div>

        <div className="p-4 bg-[#f5f2ff] rounded-lg border border-[#c7c4d8]">
          <div className="flex items-center gap-2 mb-2 text-[#3525cd]">
            <span className="material-symbols-outlined text-[20px]">sync</span>
            <h4 className="font-bold text-sm">Incremental Sync</h4>
          </div>
          <p className="text-sm text-[#464555]">
            Delta sync keeps your knowledge base current without re-indexing
            everything each run.
          </p>
        </div>
      </div>
    </div>
  );
}
