import Image from "next/image";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { FaqSection } from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

type WorkflowIconKey =
  | "upload_file"
  | "data_object"
  | "manage_search"
  | "check_circle";

const workflowNodes: Array<{
  title: string;
  description: string;
  iconLabel: WorkflowIconKey;
}> = [
  {
    title: "Multi-Modal Upload",
    description: "PDF, DOCX, and TXT ingestion",
    iconLabel: "upload_file",
  },
  {
    title: "Chunking and Vector",
    description: "Structured semantic decomposition",
    iconLabel: "data_object",
  },
  {
    title: "Retrieval Grids",
    description: "Top-k retrieval with reranking",
    iconLabel: "manage_search",
  },
  {
    title: "Trusted Answer",
    description: "Grounded response with citations",
    iconLabel: "check_circle",
  },
];

const adminHighlights = [
  {
    title: "SOC 2-aligned workflows",
    description:
      "Apply governance-ready controls across documents, chat, and evaluation operations.",
  },
  {
    title: "Usage analytics",
    description:
      "Track token usage, latency, and adoption trends for operational planning.",
  },
];

const integrationHighlights = [
  {
    title: "API-first foundation",
    description:
      "Adopt Rudix in phases with typed interfaces that fit existing workflows and delivery processes.",
  },
  {
    title: "Future-ready connectors",
    description:
      "Plan for controlled connector and MCP expansion without changing core document governance.",
  },
  {
    title: "Operator visibility",
    description:
      "Keep pipeline health and quality metrics in one view for faster incident response and tuning.",
  },
];

const faqs = [
  {
    question: "Which file types can we upload?",
    answer:
      "Rudix supports PDF, DOCX, and TXT uploads with organization-scoped processing controls.",
  },
  {
    question: "Are answers citation-backed?",
    answer:
      "Yes. Rudix returns answer references so teams can inspect source evidence and answer grounding.",
  },
  {
    question: "Can we evaluate answer quality before rollout?",
    answer:
      "Yes. Evaluation runs provide repeatable quality checks for retrieval and final answer behavior.",
  },
  {
    question: "How does Rudix support data isolation?",
    answer:
      "Rudix enforces organization-level boundaries across documents, retrieval, and user-facing workflows.",
  },
  {
    question: "Can we deploy Rudix in our own environment?",
    answer:
      "Rudix is designed for container-based deployment with environment-driven configuration and operations.",
  },
];

function WorkflowNode({
  title,
  description,
  iconLabel,
}: {
  title: string;
  description: string;
  iconLabel: WorkflowIconKey;
}) {
  return (
    <div className="relative flex w-full max-w-[220px] flex-col items-center gap-3 text-center">
      <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-[#e9e7ff] text-[#3625cd] shadow-sm">
        <WorkflowNodeIcon icon={iconLabel} />
      </div>
      <h3 className="text-sm font-bold text-[#10131c]">{title}</h3>
      <p className="text-xs leading-6 text-[#5f6375]">{description}</p>
    </div>
  );
}

function WorkflowNodeIcon({ icon }: { icon: WorkflowIconKey }) {
  if (icon === "upload_file") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M13.5 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8.5L13.5 3Z" />
        <path d="M13 3v6h6" />
        <path d="m12 17.5 2.5-2.5M12 17.5 9.5 15" />
        <path d="M12 10.5v7" />
      </svg>
    );
  }

  if (icon === "data_object") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="3.5" y="6" width="17" height="12" rx="2.5" />
        <path d="M8 10.5 6 12l2 1.5M16 10.5 18 12l-2 1.5M13.5 9.8l-3 4.4" />
      </svg>
    );
  }

  if (icon === "manage_search") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="10.5" cy="10.5" r="4.5" />
        <path d="m14 14 4.5 4.5" />
        <path d="M8.8 10.5h3.4M10.5 8.8v3.4" />
      </svg>
    );
  }

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-6 w-6"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="8" />
      <path d="m8.8 12 2.2 2.3 4.2-4.4" />
    </svg>
  );
}

function ProductHero() {
  const links = resolvePublicSiteLinks();

  return (
    <section className="mx-auto grid w-full max-w-7xl gap-10 px-4 pt-16 pb-18 lg:grid-cols-2 lg:items-center lg:gap-16 lg:px-8 lg:pt-24 lg:pb-24">
      <div>
        <div className="inline-flex items-center rounded-full border border-[#d6d2ff] bg-[#f2f0ff] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#473dd8] uppercase">
          Enterprise-Grade RAG
        </div>
        <h1 className="mt-5 text-4xl leading-tight font-black text-[#0f1220] lg:text-6xl">
          The Infrastructure for{" "}
          <span className="text-[#3525cd]">High-Fidelity</span> Document
          Intelligence
        </h1>
        <p className="mt-5 max-w-xl text-sm leading-7 text-[#505566] lg:text-base">
          Rudix orchestrates document ingestion, retrieval, grounded answers,
          and evaluation into one production-ready workflow for enterprise
          teams.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <PublicActionLink
            href={links.requestDemo}
            className="rounded-lg bg-[#3525cd] px-5 py-3 text-sm font-semibold text-white shadow-[0_16px_32px_rgba(53,37,205,0.28)] transition hover:bg-[#2b1fc1]"
          >
            Request Demo
          </PublicActionLink>
          <PublicActionLink
            href={links.app}
            className="rounded-lg border border-[#d7dbe8] bg-white px-5 py-3 text-sm font-semibold text-[#1f2433] transition hover:bg-[#f5f7fc]"
          >
            View Pipeline Explorer
          </PublicActionLink>
        </div>
      </div>
      <figure className="rounded-2xl border border-[#dfe2ea] bg-white p-4 shadow-[0_24px_56px_rgba(16,24,40,0.14)]">
        <div className="overflow-hidden rounded-xl border border-[#e6e8ef] bg-[#f9faff]">
          <Image
            src="/images/pipeline-rag-sample.png"
            alt="Rudix pipeline interface preview"
            width={1600}
            height={900}
            priority
            sizes="(max-width: 1024px) 100vw, 50vw"
            className="h-auto w-full object-cover"
          />
        </div>
        <figcaption className="sr-only">
          Product UI preview with ingestion, retrieval, and answer trace
          visibility.
        </figcaption>
      </figure>
    </section>
  );
}

function WorkflowSection() {
  return (
    <section className="border-y border-[#dee1ea] bg-white">
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="text-center">
          <p className="text-[10px] font-bold tracking-[0.2em] text-[#6e7286] uppercase">
            End-to-End Orchestration
          </p>
          <h2 className="mt-3 text-3xl font-black text-[#10131c] lg:text-5xl">
            The Rudix Engine Workflow
          </h2>
        </div>
        <div className="mt-10 flex flex-col items-center gap-0 md:flex-row md:justify-center">
          {workflowNodes.map((node, index) => (
            <div key={node.title} className="flex items-center">
              <WorkflowNode
                title={node.title}
                description={node.description}
                iconLabel={node.iconLabel}
              />
              <div
                aria-hidden="true"
                className={`workflow-connector mx-0 hidden h-[3px] w-32 rounded-full md:block ${
                  index === workflowNodes.length - 1 ? "invisible" : ""
                }`}
              >
                <span
                  className="workflow-connector__packet"
                  style={{ animationDelay: `${index * 0.35}s` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function DocumentAndAnswerSection() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-16 lg:px-8 lg:py-24">
      <div className="grid gap-16 lg:grid-cols-2 lg:items-center">
        <div className="overflow-hidden rounded-2xl border border-[#2b2c35] bg-[#171922] text-white">
          <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[#ea4335]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#fbbc05]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#34a853]" />
            </div>
            <span className="font-mono text-xs text-[#b8bfd2]">
              workspace_documents.json
            </span>
          </div>
          <div className="space-y-3 p-6">
            <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-4 py-3">
              <p className="font-mono text-xs">Annual_Report_2025.pdf</p>
              <span className="rounded-full border border-[#2cbf76]/40 bg-[#2cbf76]/20 px-2 py-1 text-[10px] font-bold text-[#7df0b3] uppercase">
                indexed
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-4 py-3">
              <p className="font-mono text-xs">Compliance_Policy.docx</p>
              <span className="rounded-full border border-[#6e8aff]/45 bg-[#6e8aff]/20 px-2 py-1 text-[10px] font-bold text-[#cad5ff] uppercase">
                parsing
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-4 py-3">
              <p className="font-mono text-xs">Operations_Handbook.txt</p>
              <span className="rounded-full border border-[#9ea6bc]/45 bg-[#9ea6bc]/20 px-2 py-1 text-[10px] font-bold text-[#e6e9f2] uppercase">
                queued
              </span>
            </div>
          </div>
        </div>
        <div>
          <h2 className="text-3xl font-black text-[#10131c] lg:text-5xl">
            Precision Document Management
          </h2>
          <p className="mt-4 text-sm leading-7 text-[#545a6c] lg:text-base">
            Handle high-volume document operations with structured ingestion
            status, reliable metadata, and clear traceability for each indexed
            asset.
          </p>
          <ul className="mt-6 space-y-3">
            <li className="flex items-start gap-3 text-sm leading-7 text-[#31364a]">
              <span className="mt-[6px] h-2 w-2 rounded-full bg-[#3525cd]" />
              Smart parsing across mixed document layouts and formats.
            </li>
            <li className="flex items-start gap-3 text-sm leading-7 text-[#31364a]">
              <span className="mt-[6px] h-2 w-2 rounded-full bg-[#3525cd]" />
              Reliable re-indexing workflows for updated policy and knowledge
              documents.
            </li>
          </ul>
        </div>
      </div>

      <div className="mt-18 grid gap-16 lg:grid-cols-2 lg:items-center">
        <div className="order-2 lg:order-1">
          <h2 className="text-3xl font-black text-[#10131c] lg:text-5xl">
            Grounded Answers with Citations
          </h2>
          <p className="mt-4 text-sm leading-7 text-[#545a6c] lg:text-base">
            Every response is tied to supporting evidence so teams can verify
            claims and inspect referenced snippets with confidence.
          </p>
          <div className="mt-6 rounded-2xl border border-[#dde1ea] bg-[#f8f9fe] p-5">
            <p className="text-xs font-semibold tracking-[0.1em] text-[#4b5170] uppercase">
              Source transparency
            </p>
            <p className="mt-2 text-sm leading-7 text-[#495063]">
              Citation markers connect each answer to original source snippets,
              giving reviewers an audit-friendly path from response to
              supporting evidence.
            </p>
          </div>
        </div>
        <div className="order-1 rounded-2xl border border-[#dbe0ea] bg-white p-5 shadow-sm lg:order-2">
          <div className="space-y-3">
            <div className="max-w-[82%] rounded-xl bg-[#eef1f8] px-4 py-3 text-sm text-[#1f2433]">
              What is our policy on cloud resource provisioning?
            </div>
            <div className="ml-auto max-w-[92%] rounded-xl bg-[#3525cd] px-4 py-3 text-sm leading-7 text-white shadow-[0_16px_32px_rgba(53,37,205,0.24)]">
              Provisioning follows the infrastructure workflow in the operations
              handbook and requires role-based review checkpoints
              <span className="ml-1 rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold">
                [Doc 4 p.12]
              </span>
              <span className="ml-1 rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold">
                [Doc 1 p.8]
              </span>
              .
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MetricsAndPipelineSection() {
  const links = resolvePublicSiteLinks();

  return (
    <section className="relative overflow-hidden bg-[#0f1118] py-16 text-white lg:py-24">
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="grid gap-4 md:grid-cols-3">
          <article className="rounded-2xl border border-white/12 bg-white/5 p-6">
            <p className="text-xs font-bold tracking-[0.14em] text-[#c5c1ff] uppercase">
              Accuracy score
            </p>
            <p className="mt-2 text-4xl font-black">98.4%</p>
            <div className="mt-4 h-1.5 rounded-full bg-white/10">
              <div className="h-full w-[98%] rounded-full bg-[#5e52ff]" />
            </div>
          </article>
          <article className="rounded-2xl border border-white/12 bg-white/5 p-6">
            <p className="text-xs font-bold tracking-[0.14em] text-[#8ce5ae] uppercase">
              Latency p99
            </p>
            <p className="mt-2 text-4xl font-black">840ms</p>
            <div className="mt-4 h-1.5 rounded-full bg-white/10">
              <div className="h-full w-[65%] rounded-full bg-[#46b873]" />
            </div>
          </article>
          <article className="rounded-2xl border border-white/12 bg-white/5 p-6">
            <p className="text-xs font-bold tracking-[0.14em] text-[#ffb18a] uppercase">
              Retrieval precision
            </p>
            <p className="mt-2 text-4xl font-black">0.96</p>
            <div className="mt-4 h-1.5 rounded-full bg-white/10">
              <div className="h-full w-[96%] rounded-full bg-[#e16a43]" />
            </div>
          </article>
        </div>

        <div className="mt-12 grid gap-10 lg:grid-cols-2 lg:items-center">
          <div>
            <h2 className="text-3xl font-black lg:text-5xl">
              Pipeline Explorer Visualizer
            </h2>
            <p className="mt-4 text-sm leading-7 text-[#cad1e5] lg:text-base">
              Trace ingestion, retrieval, and answer stages in one timeline so
              teams can debug behavior and improve quality with confidence.
            </p>
            <PublicActionLink
              href={links.app}
              className="mt-7 inline-flex rounded-lg bg-[#d4d0ff] px-5 py-3 text-sm font-semibold text-[#1f176d] transition hover:bg-[#c7c2ff]"
            >
              Open Pipeline Explorer
            </PublicActionLink>
          </div>
          <div className="rounded-3xl border border-white/12 bg-white/5 p-4">
            <Image
              src="/images/pipeline-rag-sample.png"
              alt="Pipeline dashboard preview with retrieval and latency signals"
              width={1600}
              height={900}
              sizes="(max-width: 1024px) 100vw, 50vw"
              className="h-auto w-full rounded-2xl border border-white/10"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

function AdminAndIntegrationSection() {
  const links = resolvePublicSiteLinks();

  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-16 lg:px-8 lg:py-24">
      <div className="rounded-[28px] border border-[#dbe0ec] bg-[#eceff6] p-8 lg:p-12">
        <div className="grid gap-12 lg:grid-cols-2 lg:items-start">
          <div>
            <h2 className="text-3xl font-black text-[#10131c] lg:text-5xl">
              Unified Admin Control
            </h2>
            <p className="mt-4 text-sm leading-7 text-[#555b6d] lg:text-base">
              Keep governance and operations aligned with built-in observability
              for usage, policy, and health trends.
            </p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {adminHighlights.map((item) => (
                <article
                  key={item.title}
                  className="rounded-xl border border-[#d8dce8] bg-white px-4 py-4"
                >
                  <h3 className="text-sm font-bold text-[#1e2231]">
                    {item.title}
                  </h3>
                  <p className="mt-2 text-xs leading-6 text-[#596073]">
                    {item.description}
                  </p>
                </article>
              ))}
            </div>
            <div className="mt-6 flex flex-wrap gap-3">
              <PublicActionLink
                href="/admin/usage"
                className="rounded-md bg-[#3525cd] px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-[#291ec0]"
              >
                Usage Analytics
              </PublicActionLink>
              <PublicActionLink
                href="/admin/audit-logs"
                className="rounded-md border border-[#ccd3e4] bg-white px-4 py-2.5 text-xs font-semibold text-[#232a42] transition hover:bg-[#f5f7fc]"
              >
                Audit Logs
              </PublicActionLink>
              <PublicActionLink
                href="/admin/monitoring"
                className="rounded-md border border-[#ccd3e4] bg-white px-4 py-2.5 text-xs font-semibold text-[#232a42] transition hover:bg-[#f5f7fc]"
              >
                Monitoring
              </PublicActionLink>
            </div>
          </div>
          <div className="space-y-4">
            {integrationHighlights.map((item) => (
              <article
                key={item.title}
                className="rounded-2xl border border-[#d8ddea] bg-white px-5 py-5 shadow-sm"
              >
                <h3 className="text-lg font-semibold text-[#1a1f2f]">
                  {item.title}
                </h3>
                <p className="mt-2 text-sm leading-7 text-[#5a6073]">
                  {item.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-10 rounded-[28px] bg-[linear-gradient(135deg,#2a2fe3_0%,#251bc0_52%,#3b1ed0_100%)] px-8 py-14 text-center text-white lg:px-12 lg:py-16">
        <h2 className="text-4xl font-black lg:text-6xl">
          Ready to architect your data engine?
        </h2>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <PublicActionLink
            href={links.requestDemo}
            className="rounded-lg bg-white px-5 py-3 text-sm font-semibold text-[#2d25cb] shadow-[0_12px_28px_rgba(0,0,0,0.25)] transition hover:bg-[#eff1ff]"
          >
            Speak to us
          </PublicActionLink>
          <PublicActionLink
            href={links.docs}
            className="rounded-lg border border-white/70 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            Developer Sandbox
          </PublicActionLink>
          <PublicActionLink
            href={links.security}
            className="rounded-lg border border-white/55 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/8"
          >
            View Security Page
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

export function ProductOverviewPage() {
  return (
    <>
      <ProductHero />
      <WorkflowSection />
      <DocumentAndAnswerSection />
      <MetricsAndPipelineSection />
      <AdminAndIntegrationSection />
      <FaqSection title="Product FAQ" items={faqs} />
    </>
  );
}
