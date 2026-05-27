"use client";

import { useMemo, useState } from "react";

type WorkflowKey = "pdf" | "spreadsheet" | "code" | "markdown";

type WorkflowPlaybook = {
  key: WorkflowKey;
  label: string;
  title: string;
  subtitle: string;
  icon: "document" | "table" | "code" | "notes";
  code: string;
  latency: string;
  accuracy: string;
};

const workflowPlaybooks: WorkflowPlaybook[] = [
  {
    key: "pdf",
    label: "Complex PDFs",
    title: "Complex PDF Ingestion",
    subtitle: "Advanced OCR + Layout Analysis",
    icon: "document",
    code: 'rudix.ingest("q4_report.pdf", { layout: "high_fidelity", ocr: true });',
    latency: "~140ms",
    accuracy: "99.8%",
  },
  {
    key: "spreadsheet",
    label: "Spreadsheets (CSV/XLS)",
    title: "Tabular Data Mastery",
    subtitle: "Cell-Level Precision Retrieval",
    icon: "table",
    code: 'rudix.analyze_table("financials.xlsx", { focus: "year_on_year" });',
    latency: "~85ms",
    accuracy: "99.9%",
  },
  {
    key: "code",
    label: "Source Code Repos",
    title: "Semantic Code Graph",
    subtitle: "Function & Dependency Mapping",
    icon: "code",
    code: 'rudix.index_repo("github.com/org/core", { language: "typescript" });',
    latency: "~210ms",
    accuracy: "97.5%",
  },
  {
    key: "markdown",
    label: "Markdown/Notion",
    title: "Dynamic Wiki Sync",
    subtitle: "Real-time Notion & MD Updates",
    icon: "notes",
    code: 'rudix.sync("notion_workspace_id", { interval: "realtime" });',
    latency: "~45ms",
    accuracy: "100%",
  },
];

function WorkflowIcon({ icon }: { icon: WorkflowPlaybook["icon"] }) {
  if (icon === "document") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-5 w-5"
        fill="none"
      >
        <path
          d="M8 4.5h6l3 3v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-12a2 2 0 0 1 2-2Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path d="M14 4.5V8h3" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  if (icon === "table") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-5 w-5"
        fill="none"
      >
        <rect
          x="4"
          y="5"
          width="16"
          height="14"
          rx="1.5"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M4 10h16M9 5v14M15 5v14"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "code") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-5 w-5"
        fill="none"
      >
        <path
          d="m9 8-4 4 4 4M15 8l4 4-4 4M13.5 6 10.5 18"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
      <path
        d="M7 5.5h10M7 9.5h10M7 13.5h7M7 17.5h5"
        stroke="currentColor"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export function WorkflowPlaybookSection() {
  const [activeKey, setActiveKey] = useState<WorkflowKey>("pdf");

  const activeWorkflow = useMemo(
    () =>
      workflowPlaybooks.find((playbook) => playbook.key === activeKey) ??
      workflowPlaybooks[0],
    [activeKey],
  );

  return (
    <section
      aria-labelledby="workflow-playbook-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="mb-12 text-center">
        <h2
          id="workflow-playbook-title"
          className="text-3xl font-black text-[#12141b] lg:text-5xl"
        >
          Choose Your Workflow
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
          Select a document type to see how Rudix optimizes the retrieval
          pipeline.
        </p>
      </div>

      <div className="flex flex-col items-start gap-8 lg:flex-row lg:gap-10">
        <div className="w-full space-y-3 lg:w-1/3">
          {workflowPlaybooks.map((playbook) => {
            const isActive = playbook.key === activeKey;
            return (
              <button
                key={playbook.key}
                type="button"
                aria-pressed={isActive}
                className={`group flex w-full items-center justify-between rounded-xl border px-4 py-4 text-left transition-all ${
                  isActive
                    ? "border-[#aeb6d7] bg-[#eceffd]"
                    : "border-[#d2d7e8] bg-white hover:bg-[#f5f7fc]"
                }`}
                onClick={() => {
                  setActiveKey(playbook.key);
                }}
              >
                <span className="flex items-center gap-3 text-sm font-semibold text-[#22283b]">
                  <span className="text-[#3525cd]">
                    <WorkflowIcon icon={playbook.icon} />
                  </span>
                  {playbook.label}
                </span>
                <span
                  aria-hidden="true"
                  className={`text-[#3a43d6] transition-opacity ${
                    isActive
                      ? "opacity-100"
                      : "opacity-0 group-hover:opacity-70"
                  }`}
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
                    <path
                      d="m9 6 6 6-6 6"
                      stroke="currentColor"
                      strokeWidth="1.8"
                    />
                  </svg>
                </span>
              </button>
            );
          })}
        </div>

        <div className="w-full flex-1 rounded-2xl bg-[#0f1119] p-6 text-white lg:min-h-[380px] lg:p-8">
          <div
            key={activeWorkflow.key}
            className="space-y-6 transition-all duration-300"
          >
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-[#4f58af] bg-[#1b2250] text-[#8f9bff]">
                <WorkflowIcon icon={activeWorkflow.icon} />
              </div>
              <div>
                <h3 className="text-2xl font-semibold text-white">
                  {activeWorkflow.title}
                </h3>
                <p className="text-sm text-[#b9c2e0]">
                  {activeWorkflow.subtitle}
                </p>
              </div>
            </div>

            <div className="rounded-lg border border-white/12 bg-white/5 p-4">
              <p className="mb-2 text-xs font-semibold tracking-[0.12em] text-[#c8cff0] uppercase">
                Extraction Logic
              </p>
              <code className="block overflow-x-auto text-sm text-[#dbe2ff]">
                {activeWorkflow.code}
              </code>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-white/12 bg-white/5 p-4">
                <p className="text-[10px] tracking-[0.14em] text-[#96a1c5] uppercase">
                  Latency
                </p>
                <p className="mt-1 text-xl font-bold text-white">
                  {activeWorkflow.latency}
                </p>
              </div>
              <div className="rounded-lg border border-white/12 bg-white/5 p-4">
                <p className="text-[10px] tracking-[0.14em] text-[#96a1c5] uppercase">
                  Accuracy
                </p>
                <p className="mt-1 text-xl font-bold text-white">
                  {activeWorkflow.accuracy}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
