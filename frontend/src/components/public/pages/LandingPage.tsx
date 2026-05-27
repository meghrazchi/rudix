import {
  FeatureGridSection,
  type PublicFeatureItem,
  FaqSection,
  FinalCtaBand,
  HeroSection,
  MetricsTrustStrip,
  TestimonialPlaceholderSection,
  WorkflowStripSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const capabilityItems: PublicFeatureItem[] = [
  {
    icon: "pipeline",
    title: "Pipeline Explorer",
    description:
      "Visual observability for your entire RAG lifecycle, from ingestion to generation.",
  },
  {
    icon: "ingestion",
    title: "Secure Ingestion",
    description:
      "Connect local files and cloud sources with policy-aware processing and auditability.",
  },
  {
    icon: "evaluation",
    title: "Automated Evaluation",
    description:
      "Benchmark retrieval and answer quality against evaluation sets and metrics.",
  },
];

const securityCards = [
  {
    title: "SOC 2 Type II",
    description: "Enterprise-standard controls for secure data handling.",
  },
  {
    title: "End-to-End Encryption",
    description: "AES-256 at rest and TLS 1.3 in transit across services.",
  },
  {
    title: "Private VPC",
    description:
      "Deployment options for fully isolated private-cloud infrastructure.",
  },
  {
    title: "Global Compliance",
    description: "Regional deployment and policy-ready governance controls.",
  },
];

const faqItems = [
  {
    question: "Can Rudix run inside our private cloud?",
    answer:
      "Yes. Rudix supports private VPC and isolated deployment patterns with policy-aware governance controls.",
  },
  {
    question: "How does Rudix keep answers grounded?",
    answer:
      "Rudix retrieves scoped document chunks, validates citations, and returns confidence metadata with each answer.",
  },
  {
    question: "Can we evaluate retrieval and answer quality?",
    answer:
      "Rudix includes evaluation sets, run summaries, and quality metrics to track retrieval and answer performance over time.",
  },
];

const workflowSteps = [
  {
    title: "Ingest",
    description:
      "Upload documents from local files or cloud sources with structured validation.",
  },
  {
    title: "Index",
    description:
      "Chunk and embed content into vector storage with organization-level isolation.",
  },
  {
    title: "Retrieve",
    description:
      "Run metadata-filtered retrieval and optional reranking for high-signal context.",
  },
  {
    title: "Answer",
    description:
      "Generate grounded responses with citations, confidence, and operational traces.",
  },
];

export function LandingPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <HeroSection
        badge="Enterprise-grade RAG Infrastructure"
        title={
          <>
            Scale Precision AI
            <br />
            with <span className="text-[#3a35e8]">Confidence.</span>
          </>
        }
        description="Deploy secure, production-ready Enterprise-grade RAG infrastructure. Orchestrate complex data pipelines and transform unstructured knowledge into high-precision intelligence."
        actions={[
          {
            label: "Start Free Trial",
            href: links.startTrial,
            variant: "primary",
          },
          {
            label: "Read Documentation",
            href: links.docs,
            variant: "secondary",
          },
        ]}
        imageSrc="/images/pipeline-rag-sample.png"
        imageAlt="Pipeline Explorer sample showing RAG stages, metrics, and operational status"
        imageCaption="Pipeline Explorer sample includes ingestion, chunking, storage, retrieval, reranking, and answer generation with trace details."
      />

      <MetricsTrustStrip
        heading="Powering Enterprise Intelligence"
        labels={[
          "Fortune 500",
          "Tech Giants",
          "Cybersecurity",
          "Global Finance",
        ]}
      />

      <FeatureGridSection
        sectionId="capabilities"
        title="Native RAG Capabilities"
        description="The infrastructure layer designed to handle the complexity of enterprise data and LLM orchestration."
        items={capabilityItems}
      />

      <WorkflowStripSection
        title="Built for Engineering Excellence"
        description="Deploy enterprise-grade RAG infrastructure with APIs and clients that integrate into your existing product and DevOps workflows."
        steps={workflowSteps}
      />

      <section
        aria-labelledby="security-title"
        className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
      >
        <h2
          id="security-title"
          className="text-center text-3xl font-black text-[#12141b] lg:text-5xl"
        >
          Security First Infrastructure
        </h2>
        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {securityCards.map((item) => (
            <article
              key={item.title}
              className="rounded-xl border border-[#d8dce7] bg-white px-4 py-5 text-center shadow-sm"
            >
              <p className="text-sm font-bold text-[#30344a]">{item.title}</p>
              <p className="mt-2 text-xs leading-6 text-[#676c7f]">
                {item.description}
              </p>
            </article>
          ))}
        </div>
      </section>

      <TestimonialPlaceholderSection
        quote="Rudix gave our engineering team retrieval observability and governance in weeks, not quarters."
        source="Platform Engineering Lead · Enterprise SaaS"
      />

      <FaqSection title="Frequently Asked Questions" items={faqItems} />

      <FinalCtaBand
        title="Deploy Production RAG Today"
        description="Join engineering teams using Rudix to build secure, observable, and high-confidence AI experiences."
        primaryLabel="Get Started"
        primaryHref={links.startTrial}
        secondaryLabel="Schedule Demo"
        secondaryHref={links.requestDemo}
      />
    </>
  );
}
