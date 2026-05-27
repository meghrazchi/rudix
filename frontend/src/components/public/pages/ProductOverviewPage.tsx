import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  type PublicFeatureItem,
  FaqSection,
  FeatureGridSection,
  HeroSection,
  WorkflowStripSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const capabilityItems: PublicFeatureItem[] = [
  {
    icon: "ingestion",
    title: "Documents Workspace",
    description:
      "Upload and manage PDF, DOCX, and TXT files in a single workspace with status visibility for indexed content.",
  },
  {
    icon: "evaluation",
    title: "Grounded Chat",
    description:
      "Ask questions against selected documents and receive answers built from retrieved context instead of generic output.",
  },
  {
    icon: "pipeline",
    title: "Citation Inspection",
    description:
      "Review source snippets, confidence indicators, and retrieval context to verify why an answer was produced.",
  },
  {
    icon: "evaluation",
    title: "Evaluations",
    description:
      "Run repeatable test sets to benchmark retrieval quality, answer quality, latency, and other key quality signals.",
  },
  {
    icon: "pipeline",
    title: "Pipeline Explorer",
    description:
      "Inspect ingestion and query runs step by step for faster debugging and clearer operational traceability.",
  },
  {
    icon: "governance",
    title: "Settings and Team Management",
    description:
      "Control workspace configuration, team membership, and role-scoped actions from a centralized settings experience.",
  },
  {
    icon: "governance",
    title: "Admin Governance",
    description:
      "Use admin workflows for usage analytics, audit review, policy controls, and operational readiness checks.",
  },
  {
    icon: "speed",
    title: "Optional Agentic Mode",
    description:
      "Enable guided multi-step document workflows with explicit controls and visibility when your team is ready.",
  },
];

const productFlowSteps = [
  {
    title: "Upload",
    description:
      "Users add approved PDF, DOCX, or TXT documents to the workspace.",
  },
  {
    title: "Validate",
    description:
      "Files are checked for format, size, and policy constraints before processing.",
  },
  {
    title: "Store",
    description:
      "Original files and metadata are stored with organization-scoped access boundaries.",
  },
  {
    title: "Extract",
    description:
      "Document text is extracted into structured content for downstream indexing.",
  },
  {
    title: "Chunk",
    description:
      "Content is split into retrieval-friendly chunks that preserve context and traceability.",
  },
  {
    title: "Embed",
    description:
      "Chunks are transformed into vectors for semantic search and similarity matching.",
  },
  {
    title: "Index",
    description:
      "Vectors and metadata are indexed so relevant context can be found quickly.",
  },
  {
    title: "Chat",
    description:
      "Users ask document questions from chat sessions scoped to selected indexed files.",
  },
  {
    title: "Cite",
    description:
      "Answers include supporting citations so users can verify evidence and provenance.",
  },
  {
    title: "Evaluate",
    description:
      "Evaluation runs measure quality and expose gaps before broader rollout.",
  },
  {
    title: "Monitor",
    description:
      "Operators monitor performance, confidence, and reliability over time.",
  },
];

const adminControlAreas = [
  {
    title: "Usage Analytics",
    description:
      "Track questions, tokens, estimated cost, and latency trends to manage adoption and operational efficiency.",
    href: "/admin/usage",
    linkLabel: "View Usage Analytics",
  },
  {
    title: "Audit Logs",
    description:
      "Review user and system actions with filterable events for governance and incident review workflows.",
    href: "/admin/audit-logs",
    linkLabel: "View Audit Logs",
  },
  {
    title: "Governance Controls",
    description:
      "Configure tool policies, budgets, and MCP governance settings in admin controls when enabled for your workspace.",
    href: "/admin/governance",
    linkLabel: "View Governance Settings",
  },
  {
    title: "Monitoring Readiness",
    description:
      "Follow health, alerts, and failure indicators to keep document and answer workflows resilient in production.",
    href: "/admin/monitoring",
    linkLabel: "View Monitoring",
  },
];

const integrationHighlights = [
  {
    title: "API-first by design",
    description:
      "Rudix workflows are designed around typed API contracts so product teams can integrate features in stages.",
  },
  {
    title: "Composable product surface",
    description:
      "Documents, chat, evaluations, pipeline visibility, and governance can be adopted incrementally by team maturity.",
  },
  {
    title: "Connector and MCP roadmap posture",
    description:
      "MCP and connector capabilities are available as controlled feature areas and should be enabled per deployment policy.",
  },
];

const faqs = [
  {
    question: "Which document types are supported?",
    answer:
      "Rudix supports PDF, DOCX, and TXT uploads for document indexing and grounded Q&A workflows.",
  },
  {
    question: "Do answers include citations?",
    answer:
      "Yes. Answers are designed to include source references so teams can inspect supporting evidence and context.",
  },
  {
    question: "Can we measure answer quality before rollout?",
    answer:
      "Yes. Evaluation sets and run metrics help teams benchmark retrieval and answer quality over repeated tests.",
  },
  {
    question: "How is organization data separated?",
    answer:
      "Rudix applies organization-scoped access boundaries across documents, retrieval, and user-facing product workflows.",
  },
  {
    question: "How can we deploy Rudix?",
    answer:
      "Rudix is built for container-based deployment with environment-driven configuration so teams can operate in their chosen infrastructure model.",
  },
];

function OperatorAdminSection() {
  return (
    <section
      aria-labelledby="operator-admin-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="max-w-3xl">
        <h2
          id="operator-admin-title"
          className="text-3xl font-black text-[#12141b] lg:text-5xl"
        >
          Operator and Admin Control Center
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#595d6e] lg:text-base">
          Support operations with analytics, audit visibility, governance
          controls, and monitoring surfaces aligned to production workflows.
        </p>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {adminControlAreas.map((area) => (
          <article
            key={area.title}
            className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm"
          >
            <h3 className="text-xl font-semibold text-[#171a24]">
              {area.title}
            </h3>
            <p className="mt-2 text-sm leading-7 text-[#5a6071]">
              {area.description}
            </p>
            <PublicActionLink
              href={area.href}
              className="mt-4 inline-flex text-sm font-semibold text-[#2f35dc] hover:text-[#2128b9]"
            >
              {area.linkLabel}
            </PublicActionLink>
          </article>
        ))}
      </div>
    </section>
  );
}

function IntegrationReadySection() {
  return (
    <section
      aria-labelledby="integration-ready-title"
      className="border-y border-[#d9deeb] bg-[#eff2fb]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="max-w-3xl">
          <h2
            id="integration-ready-title"
            className="text-3xl font-black text-[#12141b] lg:text-5xl"
          >
            API-first, integration-ready foundation
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#595d6e] lg:text-base">
            Integrate Rudix into existing product and platform workflows with a
            staged adoption path that balances delivery speed and governance.
          </p>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {integrationHighlights.map((highlight) => (
            <article
              key={highlight.title}
              className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm"
            >
              <h3 className="text-xl font-semibold text-[#171a24]">
                {highlight.title}
              </h3>
              <p className="mt-2 text-sm leading-7 text-[#5a6071]">
                {highlight.description}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function ProductCtaBand() {
  const links = resolvePublicSiteLinks();

  return (
    <section
      aria-labelledby="product-cta-title"
      className="bg-[linear-gradient(135deg,#2a2fe3_0%,#251bc0_52%,#3b1ed0_100%)]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-16 text-center lg:px-8 lg:py-24">
        <h2
          id="product-cta-title"
          className="text-4xl font-black text-white lg:text-6xl"
        >
          Build trusted document intelligence with Rudix
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[#d8dcff] lg:text-base">
          See how Rudix fits your document, governance, and operations workflow.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <PublicActionLink
            href={links.requestDemo}
            className="rounded-md bg-white px-5 py-3 text-sm font-semibold text-[#262ad6] shadow-[0_10px_24px_rgba(0,0,0,0.3)] transition hover:bg-[#f2f4ff]"
          >
            Request Demo
          </PublicActionLink>
          <PublicActionLink
            href={links.startTrial || links.login}
            className="rounded-md border border-white/75 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            Start Trial or Log In
          </PublicActionLink>
          <PublicActionLink
            href={links.security}
            className="rounded-md border border-white/55 px-5 py-3 text-sm font-semibold text-white/95 transition hover:bg-white/8"
          >
            View Security Page
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

export function ProductOverviewPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <HeroSection
        badge="Product Overview"
        title="AI Document Q&A for trusted enterprise decisions"
        description="Rudix turns uploaded documents into indexed, citation-backed answers with built-in evaluation, pipeline visibility, and governance-aware operations."
        actions={[
          {
            label: "Request Demo",
            href: links.requestDemo,
            variant: "primary",
          },
          {
            label: "Start Trial",
            href: links.startTrial,
            variant: "secondary",
          },
        ]}
        imageSrc="/images/pipeline-rag-sample.png"
        imageAlt="Rudix workflow and answer experience preview"
        imageCaption="Rudix pipeline and grounded answer preview"
      />

      <WorkflowStripSection
        title="How Rudix Works"
        description="Rudix follows a clear journey from document intake to trusted answers, with controls for quality and operations at each stage."
        steps={productFlowSteps}
      />

      <FeatureGridSection
        title="Capabilities Across the Product"
        description="Rudix aligns document ingestion, grounded Q&A, evaluation, observability, and governance in one unified product experience."
        items={capabilityItems}
      />

      <OperatorAdminSection />

      <IntegrationReadySection />

      <FaqSection title="Product FAQ" items={faqs} />

      <ProductCtaBand />
    </>
  );
}
