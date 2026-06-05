"use client";

import type { WizardStepProps } from "@/components/connectors/wizard/types";
import type { JiraWizardState } from "../JiraWizard.types";

type Project = {
  key: string;
  name: string;
  issueCount: number;
};

// In production these would be fetched via GET /connectors/{id}/sources after auth.
const MOCK_PROJECTS: Project[] = [
  { key: "ENG", name: "Engineering", issueCount: 1245 },
  { key: "PRD", name: "Product Roadmap", issueCount: 342 },
  { key: "DSGN", name: "Design Ops", issueCount: 89 },
  { key: "CS", name: "Customer Support", issueCount: 5820 },
];

export function JiraProjectsStep({ state, onChange }: WizardStepProps<JiraWizardState>) {
  const selected = new Set(state.selectedProjectKeys);

  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    onChange({ selectedProjectKeys: Array.from(next) });
  }

  function selectAll() {
    onChange({ selectedProjectKeys: MOCK_PROJECTS.map((p) => p.key) });
  }

  function clearAll() {
    onChange({ selectedProjectKeys: [] });
  }

  const allSelected = selected.size === MOCK_PROJECTS.length;

  return (
    <div>
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[#1b1b24] mb-1">
            Select Projects
          </h2>
          <p className="text-base text-[#464555]">
            Choose which Jira projects to include in the retrieval index.
          </p>
        </div>
        <button
          type="button"
          onClick={allSelected ? clearAll : selectAll}
          className="text-sm font-semibold text-[#3525cd] hover:underline shrink-0"
        >
          {allSelected ? "Clear all" : "Select all"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {MOCK_PROJECTS.map((project) => {
          const isSelected = selected.has(project.key);
          return (
            <label
              key={project.key}
              className={`flex items-center gap-4 p-4 border rounded-xl cursor-pointer transition-all ${
                isSelected
                  ? "border-[#3525cd] bg-[#3525cd]/5"
                  : "border-[#c7c4d8] hover:border-[#3525cd]/40 bg-white"
              }`}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => toggle(project.key)}
                className="w-5 h-5 rounded border-[#c7c4d8] text-[#3525cd] focus:ring-[#3525cd]"
              />
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm text-[#1b1b24]">
                  {project.name}{" "}
                  <span className="font-mono text-xs text-[#777587]">
                    ({project.key})
                  </span>
                </div>
                <div className="text-xs text-[#464555] mt-0.5">
                  {project.issueCount.toLocaleString()} issues
                </div>
              </div>
              {isSelected && (
                <span className="material-symbols-outlined text-[#3525cd] shrink-0">
                  check_circle
                </span>
              )}
            </label>
          );
        })}
      </div>

      {selected.size === 0 && (
        <p className="mt-4 text-sm text-[#777587] text-center">
          Select at least one project to continue.
        </p>
      )}
    </div>
  );
}
