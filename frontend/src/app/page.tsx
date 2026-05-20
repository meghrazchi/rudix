import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

type CapabilityCard = {
  icon: "pipeline" | "ingestion" | "evaluation";
  title: string;
  description: string;
};

type SecurityCard = {
  title: string;
  description: string;
};

type SurfaceLink = {
  label: string;
  href: string;
};

type LandingLinks = {
  product: string;
  solutions: string;
  pricing: string;
  login: string;
  requestDemo: string;
  startTrial: string;
  readDocs: string;
  getStarted: string;
  scheduleDemo: string;
  footerStatus: string;
  footerContact: string;
};

const FOCUS_RING_CLASS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3a35e8] focus-visible:ring-offset-2 focus-visible:ring-offset-transparent";
const LOGO_MARK_SRC = "/brand/rudix-mark.svg";
const PIPELINE_SAMPLE_SRC = "/images/pipeline-rag-sample.png";

export const metadata: Metadata = {
  title: "Rudix | Enterprise RAG Infrastructure",
  description:
    "Rudix is a production-ready enterprise RAG platform with secure ingestion, grounded chat, evaluation analytics, and pipeline observability.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "Rudix | Enterprise RAG Infrastructure",
    description:
      "Deploy enterprise-grade RAG infrastructure with secure ingestion, grounded answers, and operational observability.",
    type: "website",
    url: "/",
  },
  robots: {
    index: true,
    follow: true,
  },
};

const capabilities: CapabilityCard[] = [
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

const securityCards: SecurityCard[] = [
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

const trustLogos = [
  "Fortune 500",
  "Tech Giant",
  "Cyber Sec",
  "Global Fin",
] as const;

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href) || /^mailto:/i.test(href);
}

function resolveLandingLinks(): LandingLinks {
  const docsUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_DOCUMENTATION_URL) ??
    trimToNull(process.env.NEXT_PUBLIC_HELP_DOCS_URL) ??
    "/documents";
  const demoUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_DEMO_URL) ?? "/login";
  const trialUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_TRIAL_URL) ?? "/signup";
  const productUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_PRODUCT_URL) ?? "/dashboard";
  const solutionsUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_SOLUTIONS_URL) ?? "/documents";
  const pricingUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_PRICING_URL) ?? "/settings";
  const statusUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_STATUS_URL) ??
    "/admin/system-health";
  const contactUrl =
    trimToNull(process.env.NEXT_PUBLIC_LANDING_CONTACT_URL) ??
    trimToNull(process.env.NEXT_PUBLIC_SUPPORT_URL) ??
    "/settings";

  return {
    product: productUrl,
    solutions: solutionsUrl,
    pricing: pricingUrl,
    login: "/login",
    requestDemo: demoUrl,
    startTrial: trialUrl,
    readDocs: docsUrl,
    getStarted: trialUrl,
    scheduleDemo: demoUrl,
    footerStatus: statusUrl,
    footerContact: contactUrl,
  };
}

function ActionLink({
  href,
  className,
  children,
  ariaLabel,
}: {
  href: string;
  className: string;
  children: React.ReactNode;
  ariaLabel?: string;
}) {
  if (isExternalHref(href)) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer noopener"
        className={`${className} ${FOCUS_RING_CLASS}`}
        aria-label={ariaLabel}
      >
        {children}
      </a>
    );
  }

  return (
    <Link
      href={href}
      className={`${className} ${FOCUS_RING_CLASS}`}
      aria-label={ariaLabel}
    >
      {children}
    </Link>
  );
}

function StatusPill({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-[#e2def7] bg-[#f2f0ff] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#5a53a4] uppercase">
      {label}
    </span>
  );
}

function CapabilityIcon({ icon }: { icon: CapabilityCard["icon"] }) {
  if (icon === "pipeline") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="4" y="5" width="16" height="14" rx="2.5" />
        <path d="M4 9h16M7.5 7h0M10 7h0" />
        <path d="M8 14h3.5M12.5 14h3.5M10.2 16h3.6" />
      </svg>
    );
  }

  if (icon === "ingestion") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 3.8L6.5 6.3v4.4c0 3.9 2.2 7.5 5.5 9 3.3-1.5 5.5-5.1 5.5-9V6.3L12 3.8Z" />
        <path d="m9.6 11.9 1.8 1.8 3-3" />
      </svg>
    );
  }

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="7" />
      <path d="M12 8.7v3.7l2.5 1.7" />
      <path d="M9.2 15.4h5.6" />
    </svg>
  );
}

export default function Home() {
  const links = resolveLandingLinks();
  const navLinks: SurfaceLink[] = [
    { label: "Product", href: links.product },
    { label: "Solutions", href: links.solutions },
    { label: "Pricing", href: links.pricing },
  ];

  return (
    <main className="min-h-screen bg-[#f2f3f6] text-[#13141a]">
      <header className="border-b border-[#dbdde4] bg-[#f2f3f6]/95">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-4 lg:px-8">
          <div className="flex items-center gap-8">
            <Link
              href="/"
              className={`flex items-center gap-2 ${FOCUS_RING_CLASS}`}
              aria-label="Rudix home"
            >
              <Image
                src={LOGO_MARK_SRC}
                alt="Rudix logo"
                width={24}
                height={24}
                className="h-6 w-6"
              />
              <span className="text-sm font-bold text-[#11131a]">Rudix</span>
            </Link>
            <nav
              aria-label="Primary navigation"
              className="hidden items-center gap-6 md:flex"
            >
              {navLinks.map((item) => (
                <ActionLink
                  key={item.label}
                  href={item.href}
                  className="text-xs font-medium text-[#4e5160] transition hover:text-[#25283a]"
                >
                  {item.label}
                </ActionLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <ActionLink
              href={links.login}
              className="text-xs font-semibold text-[#2e3141] transition hover:text-black"
            >
              Login
            </ActionLink>
            <ActionLink
              href={links.requestDemo}
              className="rounded-md bg-[#3a35e8] px-3 py-2 text-xs font-semibold text-white transition hover:bg-[#2d2ad1]"
            >
              Request Demo
            </ActionLink>
          </div>
        </div>
      </header>

      <section
        aria-labelledby="landing-hero-title"
        className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-12 lg:grid-cols-2 lg:items-center lg:gap-12 lg:px-8 lg:py-16"
      >
        <div>
          <StatusPill label="Enterprise-grade RAG Infrastructure" />
          <h1
            id="landing-hero-title"
            className="mt-6 text-4xl leading-tight font-black text-[#101218] lg:text-6xl"
          >
            Scale Precision AI
            <br />
            with <span className="text-[#3a35e8]">Confidence.</span>
          </h1>
          <p className="mt-5 max-w-xl text-sm leading-7 text-[#505465] lg:text-base">
            Deploy secure, production-ready Enterprise-grade RAG infrastructure.
            Orchestrate complex data pipelines and transform unstructured
            knowledge into high-precision intelligence.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ActionLink
              href={links.startTrial}
              className="rounded-md bg-[#3a35e8] px-5 py-3 text-sm font-semibold text-white shadow-[0_6px_20px_rgba(58,53,232,0.35)] transition hover:bg-[#2d2ad1]"
            >
              Start Free Trial
            </ActionLink>
            <ActionLink
              href={links.readDocs}
              className="rounded-md border border-[#c7cad6] bg-white px-5 py-3 text-sm font-semibold text-[#2a2f40] transition hover:bg-[#f6f7fb]"
            >
              Read Documentation
            </ActionLink>
          </div>
        </div>

        <figure
          aria-label="Pipeline Explorer sample showing RAG stages, metrics, and operational status"
          className="rounded-2xl border border-[#dfe2ea] bg-white p-4 shadow-[0_22px_50px_rgba(10,15,35,0.14)]"
        >
          <div className="overflow-hidden rounded-xl border border-[#e6e7ef] bg-[#fbfbfe]">
            <Image
              src={PIPELINE_SAMPLE_SRC}
              alt="Rudix pipeline explorer with graph and node details"
              width={1600}
              height={900}
              priority
              sizes="(max-width: 1024px) 100vw, 50vw"
              className="h-auto w-full object-cover"
            />
          </div>
          <figcaption className="sr-only">
            Pipeline Explorer sample includes ingestion, chunking, storage,
            retrieval, reranking, and answer generation with trace details.
          </figcaption>
        </figure>
      </section>

      <section className="border-y border-[#dde0e8] bg-[#eff1f5] py-8">
        <div className="mx-auto w-full max-w-7xl px-4 text-center lg:px-8">
          <p className="text-[10px] font-bold tracking-[0.24em] text-[#666a7d] uppercase">
            Powering Enterprise Intelligence
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-8">
            {trustLogos.map((logo) => (
              <p
                key={logo}
                className="text-xs font-semibold tracking-[0.08em] text-[#7a7f91] uppercase"
              >
                {logo}
              </p>
            ))}
          </div>
        </div>
      </section>

      <section
        id="capabilities"
        aria-labelledby="capabilities-title"
        className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
      >
        <div className="text-center">
          <h2
            id="capabilities-title"
            className="text-3xl font-black text-[#12141b] lg:text-5xl"
          >
            Native RAG Capabilities
          </h2>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[#595d6e]">
            The infrastructure layer designed to handle the complexity of
            enterprise data and LLM orchestration.
          </p>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {capabilities.map((item) => (
            <article
              key={item.title}
              className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm"
            >
              <div className="mb-4 inline-flex h-8 w-8 items-center justify-center rounded-md bg-[#ecebff] text-[#4338ff]">
                <CapabilityIcon icon={item.icon} />
              </div>
              <h3 className="text-2xl font-semibold text-[#171a24]">
                {item.title}
              </h3>
              <p className="mt-3 text-sm leading-7 text-[#5a6071]">
                {item.description}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="engineering-title" className="bg-[#1e242f]">
        <div className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-14 lg:grid-cols-2 lg:items-center lg:gap-12 lg:px-8 lg:py-20">
          <figure
            role="img"
            aria-label="Terminal-like code sample showing Rudix client retrieval flow"
            className="rounded-xl border border-[#303847] bg-[#111722] p-4 shadow-[0_20px_40px_rgba(0,0,0,0.35)]"
          >
            <p className="mb-2 text-[10px] text-[#8d96ac]">rudix-sdk / main</p>
            <pre className="overflow-x-auto text-[11px] leading-6 text-[#d3d9e8]">
              {`import rudix as rx

client = rx.Client(endpoint="https://rag.enterprise.internal")

query = client.document_retrieval(
  context = client.retrieve(
    query="SOC2 compliance requirements",
    top_k=8,
    rerank=True
  )
)

print(query.answer_confidence)`}
            </pre>
          </figure>
          <div>
            <h2
              id="engineering-title"
              className="text-4xl font-black text-white lg:text-5xl"
            >
              Built for Engineering Excellence
            </h2>
            <p className="mt-4 text-sm leading-7 text-[#c7cede] lg:text-base">
              Deploy enterprise-grade RAG infrastructure with APIs and clients
              that integrate into your existing product and DevOps workflows.
            </p>
            <ul className="mt-6 space-y-4 text-sm text-[#dce3f2]">
              <li className="rounded-lg border border-[#384154] bg-[#252d3b] px-4 py-3">
                GitLab-integrated dashboards and version-controlled prompt
                pipelines.
              </li>
              <li className="rounded-lg border border-[#384154] bg-[#252d3b] px-4 py-3">
                Scalable API architecture with background workers and retries.
              </li>
            </ul>
          </div>
        </div>
      </section>

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

      <section
        aria-labelledby="cta-title"
        className="bg-[linear-gradient(135deg,#2a2fe3_0%,#251bc0_52%,#3b1ed0_100%)]"
      >
        <div className="mx-auto w-full max-w-7xl px-4 py-16 text-center lg:px-8 lg:py-24">
          <h2
            id="cta-title"
            className="text-4xl font-black text-white lg:text-6xl"
          >
            Deploy Production RAG Today
          </h2>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[#d8dcff] lg:text-base">
            Join engineering teams using Rudix to build secure, observable, and
            high-confidence AI experiences.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <ActionLink
              href={links.getStarted}
              className="rounded-md bg-white px-5 py-3 text-sm font-semibold text-[#262ad6] shadow-[0_10px_24px_rgba(0,0,0,0.3)] transition hover:bg-[#f2f4ff]"
            >
              Get Started
            </ActionLink>
            <ActionLink
              href={links.scheduleDemo}
              className="rounded-md border border-white/75 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              Schedule Demo
            </ActionLink>
          </div>
        </div>
      </section>

      <footer className="border-t border-[#d8dbe5] bg-[#f2f3f6]">
        <div className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-10 lg:grid-cols-[1.3fr_1fr_1fr_1fr] lg:px-8">
          <div>
            <div className="flex items-center gap-2">
              <Image
                src={LOGO_MARK_SRC}
                alt="Rudix logo"
                width={24}
                height={24}
                className="h-6 w-6"
              />
              <span className="text-sm font-bold text-[#11131a]">Rudix</span>
            </div>
            <p className="mt-3 max-w-xs text-xs leading-6 text-[#626778]">
              Enterprise-grade RAG infrastructure for secure, scalable knowledge
              retrieval and AI applications.
            </p>
            <p className="mt-4 text-xs text-[#7c8194]">
              © 2026 Rudix AI. All rights reserved.
            </p>
          </div>

          <div>
            <p className="text-xs font-bold tracking-wide text-[#4f5467] uppercase">
              Product
            </p>
            <ul className="mt-3 space-y-2 text-sm text-[#4b4f60]">
              <li>
                <ActionLink
                  href="/rag-pipeline"
                  className="transition hover:text-[#25283a]"
                >
                  Pipeline Explorer
                </ActionLink>
              </li>
              <li>
                <ActionLink
                  href={links.readDocs}
                  className="transition hover:text-[#25283a]"
                >
                  API Reference
                </ActionLink>
              </li>
              <li>
                <ActionLink
                  href={links.readDocs}
                  className="transition hover:text-[#25283a]"
                >
                  Security Docs
                </ActionLink>
              </li>
            </ul>
          </div>

          <div>
            <p className="text-xs font-bold tracking-wide text-[#4f5467] uppercase">
              Company
            </p>
            <ul className="mt-3 space-y-2 text-sm text-[#4b4f60]">
              <li>
                <ActionLink
                  href={links.product}
                  className="transition hover:text-[#25283a]"
                >
                  About Us
                </ActionLink>
              </li>
              <li>
                <ActionLink
                  href={links.solutions}
                  className="transition hover:text-[#25283a]"
                >
                  Careers
                </ActionLink>
              </li>
              <li>
                <ActionLink
                  href="/forbidden"
                  className="transition hover:text-[#25283a]"
                >
                  Trust Center
                </ActionLink>
              </li>
            </ul>
          </div>

          <div>
            <p className="text-xs font-bold tracking-wide text-[#4f5467] uppercase">
              Support
            </p>
            <ul className="mt-3 space-y-2 text-sm text-[#4b4f60]">
              <li>
                <ActionLink
                  href={links.readDocs}
                  className="transition hover:text-[#25283a]"
                >
                  Documentation
                </ActionLink>
              </li>
              <li>
                <ActionLink
                  href={links.footerStatus}
                  className="transition hover:text-[#25283a]"
                >
                  Status Page
                </ActionLink>
              </li>
              <li>
                <ActionLink
                  href={links.footerContact}
                  className="transition hover:text-[#25283a]"
                >
                  Contact
                </ActionLink>
              </li>
            </ul>
          </div>
        </div>
      </footer>
    </main>
  );
}
