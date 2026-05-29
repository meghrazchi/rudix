"use client";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

// ── icons ────────────────────────────────────────────────────────────────────

function IconRepeat() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
      <path
        d="M17 2l4 4-4 4M3 11V9a4 4 0 014-4h14M7 22l-4-4 4-4M21 13v2a4 4 0 01-4 4H3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconSearchOff() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
      <path
        d="M16 16l4 4M8 8l6 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconShield() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
      <path
        d="M12 3.8L6.5 6.3v4.4c0 3.9 2.2 7.5 5.5 9 3.3-1.5 5.5-5.1 5.5-9V6.3L12 3.8Z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M9.5 12l2 2 3.5-4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconDocument() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path
        d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path d="M14 2v6h6M8 13h8M8 17h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function IconLock() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
      <rect x="3" y="11" width="18" height="11" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M7 11V7a5 5 0 0110 0v4" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function IconHistory() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
      <path d="M3 12a9 9 0 109-9 9 9 0 00-9 9z" stroke="currentColor" strokeWidth="2" />
      <path d="M12 7v5l3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function IconUpload() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconChevron() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 shrink-0 transition-transform duration-200 group-open:rotate-180" fill="none">
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── sections ─────────────────────────────────────────────────────────────────

function HRHeroSection({ demoHref }: { demoHref: string }) {
  return (
    <section
      aria-labelledby="hr-hero-title"
      className="relative overflow-hidden bg-white pt-20 pb-28"
    >
      <div className="absolute -top-32 -right-32 h-96 w-96 rounded-full bg-[#3a35e8]/5 blur-3xl" />
      <div className="mx-auto grid w-full max-w-7xl items-center gap-16 px-4 lg:grid-cols-2 lg:px-8">
        <div className="relative z-10">
          <span className="inline-block rounded-full bg-[#ecebff] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#3a35e8] uppercase">
            Enterprise HR Solutions
          </span>
          <h1
            id="hr-hero-title"
            className="mt-6 text-4xl font-black leading-tight tracking-tight text-[#0f1117] lg:text-5xl"
          >
            HR answers from your actual policies.
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-[#505465]">
            Help employees find answers from handbooks, benefits guides, leave
            policies, onboarding documents, and internal HR processes with
            surgical precision.
          </p>
          <div className="mt-8 flex flex-wrap gap-4">
            <PublicActionLink
              href={demoHref}
              className="rounded-md bg-[#3a35e8] px-7 py-3.5 text-sm font-semibold text-white shadow-[0_8px_24px_rgba(58,53,232,0.35)] transition hover:bg-[#2d2ad1] active:scale-95"
            >
              Speak to us about HR
            </PublicActionLink>
            <PublicActionLink
              href="/solutions"
              className="rounded-md border border-[#d0d5e4] px-7 py-3.5 text-sm font-semibold text-[#343a50] transition hover:bg-[#f4f6fb]"
            >
              All solutions
            </PublicActionLink>
          </div>
        </div>

        <div className="relative">
          <div
            className="overflow-hidden rounded-xl border border-[#e2e2e9]/50 bg-white/70 p-2 shadow-2xl"
            style={{ backdropFilter: "blur(20px)" }}
          >
            <div className="rounded-lg border border-[#e6e7ef] bg-[#f8f8fc] p-6">
              <p className="mb-4 text-[11px] font-bold tracking-widest text-[#3a35e8] uppercase">
                Policy assistant · HR workspace
              </p>
              <div className="space-y-3">
                {[
                  "What is the parental leave policy by region?",
                  "Which onboarding documents are required before day one?",
                  "What is the remote work reimbursement limit?",
                ].map((q) => (
                  <div
                    key={q}
                    className="rounded-lg bg-white p-3 text-sm text-[#252a3b] shadow-sm"
                  >
                    {q}
                  </div>
                ))}
              </div>
              <div className="mt-4 rounded-lg border-l-4 border-[#3a35e8] bg-[#ecebff]/60 p-3">
                <p className="text-xs font-semibold text-[#3a35e8]">
                  Rudix HR Engine
                </p>
                <p className="mt-1 text-xs leading-5 text-[#252a3b]">
                  You are eligible for 16 weeks of fully paid leave…{" "}
                  <span className="font-medium text-[#3a35e8]">
                    [Global Benefits Guide, p. 42]
                  </span>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function HRProblemSection() {
  const problems = [
    {
      icon: <IconRepeat />,
      iconBg: "bg-red-100 text-red-700",
      title: "Repeated Questions",
      body: "Employees ask the same questions daily, draining bandwidth from strategic HR initiatives.",
    },
    {
      icon: <IconSearchOff />,
      iconBg: "bg-[#e8e7ed] text-[#464555]",
      title: "Hard to Search",
      body: "Static PDFs and messy intranet pages make finding the one true answer nearly impossible for staff.",
    },
    {
      icon: <IconShield />,
      iconBg: "bg-[#d1fae5] text-[#065f46]",
      title: "Accuracy Gaps",
      body: "Outdated documents lead to conflicting information. Rudix ensures answers come from current versions.",
    },
  ];

  return (
    <section
      aria-labelledby="problem-title"
      className="bg-[#f4f3f9] py-24"
    >
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="mb-14 text-center">
          <h2
            id="problem-title"
            className="text-3xl font-black text-[#0f1117] lg:text-4xl"
          >
            HR teams answer the same questions every week.
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-[#505465]">
            Manual triage is the bottleneck of scaling enterprise culture. Stop
            being a search engine for your own documents.
          </p>
        </div>
        <ul className="grid gap-6 md:grid-cols-3">
          {problems.map((p) => (
            <li
              key={p.title}
              className="rounded-xl border border-[#d8dce7] bg-white p-8 transition hover:border-[#3a35e8]"
            >
              <div
                className={`mb-6 inline-flex h-11 w-11 items-center justify-center rounded-lg ${p.iconBg}`}
              >
                {p.icon}
              </div>
              <h3 className="text-lg font-semibold text-[#0f1117]">{p.title}</h3>
              <p className="mt-3 text-sm leading-6 text-[#505465]">{p.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function HRFlowSection() {
  return (
    <section aria-labelledby="flow-title" className="bg-white py-24">
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="mb-14">
          <h2
            id="flow-title"
            className="text-3xl font-black text-[#0f1117] lg:text-4xl"
          >
            Policy infrastructure flow
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#505465]">
            How Rudix transforms HR documents into grounded answers.
          </p>
        </div>

        <ol className="grid gap-6 lg:grid-cols-4">
          <li className="flex flex-col rounded-xl border border-[#d8dce7] bg-[#f4f3f9] p-7">
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#3a35e8] uppercase">
              Step 01
            </p>
            <h3 className="mt-3 text-base font-semibold text-[#0f1117]">
              HR uploads policies
            </h3>
            <p className="mt-2 grow text-sm leading-6 text-[#505465]">
              Securely ingest PDFs, DOCX, or text files into the Rudix workspace.
            </p>
            <div className="mt-7 rounded border border-[#d8dce7] bg-white p-3 font-mono text-xs text-[#505465]">
              <div className="flex items-center gap-2 mb-1.5">
                <IconDocument />
                <span>policy_v4.pdf</span>
              </div>
              <div className="flex items-center gap-2 text-[#3a35e8]">
                <IconUpload />
                <span>Uploading… 82%</span>
              </div>
            </div>
          </li>

          <li className="flex flex-col rounded-xl bg-[#0f1117] p-7 text-white">
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#c3c0ff] uppercase">
              Step 02
            </p>
            <h3 className="mt-3 text-base font-semibold">Rudix indexes</h3>
            <p className="mt-2 grow text-sm leading-6 text-[#c7cede]">
              Advanced RAG architecture breaks text into semantic vector
              embeddings for precise retrieval.
            </p>
            <div className="mt-7">
              <svg viewBox="0 0 200 32" className="w-full" aria-hidden="true">
                {/* Track */}
                <path
                  id="hr-packet-track"
                  d="M10,16 Q100,16 190,16"
                  fill="none"
                  stroke="#3a35e8"
                  strokeWidth="1"
                  strokeOpacity="0.25"
                />
                {/* Three line-shaped packets travel the same path, staggered */}
                {[0, 2, 4, 6].map((delay) => (
                  <rect key={delay} x="-8" y="-1.5" width="16" height="3" rx="1.5" fill="#3a35e8">
                    <animateMotion
                      dur="8s"
                      repeatCount="indefinite"
                      begin={`${delay}s`}
                      rotate="auto"
                    >
                      <mpath href="#hr-packet-track" />
                    </animateMotion>
                  </rect>
                ))}
              </svg>
            </div>
          </li>

          <li className="flex flex-col rounded-xl border border-[#d8dce7] bg-[#f4f3f9] p-7">
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#3a35e8] uppercase">
              Step 03
            </p>
            <h3 className="mt-3 text-base font-semibold text-[#0f1117]">
              Employees ask
            </h3>
            <p className="mt-2 grow text-sm leading-6 text-[#505465]">
              Staff query the assistant in plain language from any interface.
            </p>
            <div className="mt-7 rounded-full border border-[#d8dce7] bg-white px-4 py-2.5 text-xs italic text-[#505465] shadow-sm">
              "What is the parental leave policy?"
            </div>
          </li>

          <li className="flex flex-col rounded-xl bg-[#3a35e8] p-7 text-white">
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#c3c0ff] uppercase">
              Step 04
            </p>
            <h3 className="mt-3 text-base font-semibold">Cited answers</h3>
            <p className="mt-2 grow text-sm leading-6 text-[#d8dcff]">
              Rudix provides grounded answers with verbatim citations from the
              source document.
            </p>
            <div className="mt-7 rounded bg-white/10 p-3 text-xs leading-5 text-[#e8e6ff]">
              "You are eligible for 16 weeks…{" "}
              <span className="font-medium">[Leave Policy p. 14]</span>"
            </div>
          </li>
        </ol>
      </div>
    </section>
  );
}

function HRDocumentSourcesSection() {
  const sources = [
    { label: "Employee handbook" },
    { label: "Benefits enrollment guide" },
    { label: "Leave and time-off policies" },
    { label: "Expense and remote work SOPs" },
    { label: "Remote work policy" },
    { label: "Onboarding checklist" },
    { label: "Role transition guides" },
    { label: "Training materials" },
  ];

  return (
    <section
      aria-labelledby="doc-sources-title"
      className="bg-[#e8e7ed] py-24"
    >
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="grid gap-16 lg:grid-cols-2 lg:items-center">
          <div>
            <h2
              id="doc-sources-title"
              className="text-3xl font-black text-[#0f1117] lg:text-4xl"
            >
              Supported document sources
            </h2>
            <p className="mt-4 text-sm leading-7 text-[#505465]">
              Whether it's a 200-page handbook or a one-page memo, Rudix
              processes every nuance of your organizational knowledge.
            </p>
            <ul className="mt-8 grid gap-3 sm:grid-cols-2">
              {sources.map((s) => (
                <li
                  key={s.label}
                  className="flex items-center gap-3 rounded-lg border border-[#d8dce7] bg-white p-4"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[#ecebff] text-[#3a35e8]">
                    <IconDocument />
                  </span>
                  <span className="text-sm font-medium text-[#252a3b]">
                    {s.label}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-[#d8dce7] bg-white p-8 shadow-sm">
            <p className="text-[11px] font-bold tracking-widest text-[#3a35e8] uppercase">
              Example Q&amp;A
            </p>
            <div className="mt-4 space-y-4 text-sm">
              <div className="rounded-lg bg-[#f4f3f9] p-4">
                <p className="font-semibold text-[#0f1117]">
                  "How many days of sick leave per month?"
                </p>
                <div className="mt-3 border-l-4 border-[#3a35e8] pl-3 text-[#505465]">
                  Employees accrue 1.5 sick days per month up to 18 days per
                  year.
                  <br />
                  <span className="mt-1 block text-xs font-medium text-[#3a35e8]">
                    [Leave Policy 2024, §3.2]
                  </span>
                </div>
              </div>
              <div className="rounded-lg bg-[#f4f3f9] p-4">
                <p className="font-semibold text-[#0f1117]">
                  "What is the remote work expense limit?"
                </p>
                <div className="mt-3 border-l-4 border-[#3a35e8] pl-3 text-[#505465]">
                  Up to $75/month for home-office expenses with manager approval.
                  <br />
                  <span className="mt-1 block text-xs font-medium text-[#3a35e8]">
                    [Remote Work SOP, §4]
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function HRExampleQuestionsSection() {
  const questions = [
    {
      initials: "JD",
      avatarBg: "bg-[#e8e7ed]",
      question: "What is the parental leave policy?",
      answer:
        "Our policy provides 16 weeks of fully paid leave for primary caregivers. This applies to birth, adoption, or foster placement. Eligibility begins after 6 months of continuous employment.",
      citation: "Global Benefits Guide, p. 42",
    },
    {
      initials: "AK",
      avatarBg: "bg-[#ecebff]",
      question: "How many vacation days do I get?",
      answer:
        "Standard employees receive 25 days per calendar year, prorated based on start date. Up to 5 days can be carried over to the next year.",
      citation: "Employee Handbook, §6.1",
    },
    {
      initials: "MR",
      avatarBg: "bg-[#d1fae5]",
      question: "How do I submit an expense claim?",
      answer:
        "Log into the expense portal with your company email and submit receipts by the 25th of each month for reimbursement in the next pay cycle.",
      citation: "Expense Policy, §2",
    },
    {
      initials: "SL",
      avatarBg: "bg-[#fde68a]",
      question:
        "What happens if my question is not covered in the handbook?",
      answer:
        "Rudix will surface a low-confidence or not-found response and suggest contacting HR directly. Answer quality is tracked so coverage gaps can be addressed in the next policy update.",
      citation: "No direct source — low confidence indicated",
    },
  ];

  return (
    <section
      aria-labelledby="questions-title"
      className="bg-white py-24"
    >
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="mb-12">
          <span className="text-[11px] font-bold tracking-[0.12em] text-[#3a35e8] uppercase">
            Employee experience
          </span>
          <h2
            id="questions-title"
            className="mt-2 text-3xl font-black text-[#0f1117] lg:text-4xl"
          >
            Instant clarity for every query.
          </h2>
        </div>

        <ul className="mx-auto max-w-3xl space-y-4">
          {questions.map((q) => (
            <li key={q.question}>
              <details className="group rounded-xl border border-[#d8dce7] bg-white">
                <summary className="flex cursor-pointer list-none items-start gap-5 p-5">
                  <div
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold text-[#252a3b] ${q.avatarBg}`}
                  >
                    {q.initials}
                  </div>
                  <p className="flex-1 pt-1.5 text-sm font-semibold text-[#0f1117]">
                    "{q.question}"
                  </p>
                  <IconChevron />
                </summary>
                <div className="border-t border-[#ecebff] px-5 pb-5 pt-4">
                  <div className="rounded-lg border-l-4 border-[#3a35e8] bg-[#ecebff]/40 p-4">
                    <p className="text-[10px] font-bold tracking-widest text-[#3a35e8] uppercase">
                      Rudix HR Engine
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[#252a3b]">
                      {q.answer}
                    </p>
                    <p className="mt-3 border-t border-[#3a35e8]/20 pt-2 text-[11px] text-[#505465]">
                      📄 {q.citation}
                    </p>
                  </div>
                </div>
              </details>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function HRSecuritySection() {
  const features = [
    { icon: <IconLock />, label: "End-to-end encryption at rest and in transit" },
    { icon: <IconShield />, label: "Role-scoped access — employees only see their content" },
    { icon: <IconHistory />, label: "Complete audit log for every query and document action" },
  ];

  return (
    <section aria-labelledby="security-title" className="py-24">
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="overflow-hidden rounded-2xl bg-[#0f1117] lg:grid lg:grid-cols-2">
          <div className="p-10 lg:p-12">
            <h2
              id="security-title"
              className="text-2xl font-black text-white lg:text-3xl"
            >
              Built for HR data sensitivity
            </h2>
            <p className="mt-4 text-sm leading-7 text-[#c7cede]">
              HR documents contain sensitive employee information. Rudix is
              built with role-aware access, data governance, and clear
              boundaries between what Rudix answers and what your HR team
              owns.
            </p>
            <ul className="mt-8 space-y-5">
              {features.map((f) => (
                <li
                  key={f.label}
                  className="flex items-start gap-3 text-sm text-[#c7cede]"
                >
                  <span className="mt-0.5 shrink-0 text-[#c3c0ff]">
                    {f.icon}
                  </span>
                  {f.label}
                </li>
              ))}
            </ul>
          </div>

          <div className="border-t border-white/5 bg-[#0a0a0f] p-10 lg:border-t-0 lg:border-l lg:p-12">
            <div className="mb-5 flex gap-2">
              <span className="h-3 w-3 rounded-full bg-red-500" />
              <span className="h-3 w-3 rounded-full bg-yellow-500" />
              <span className="h-3 w-3 rounded-full bg-green-500" />
            </div>
            <pre className="font-mono text-xs leading-6 text-[#c7cede]">
              <span className="text-[#c3c0ff]">POST</span>{" "}
              /api/v1/documents/upload{"\n"}
              {"  "}<span className="text-[#75db94]">Authorization</span>: Bearer $TOKEN{"\n"}
              {"  "}Content-Type: multipart/form-data{"\n\n"}
              <span className="text-[#9aa5c0]"># Response</span>{"\n"}
              {"{"}
              {"\n"}
              {"  "}<span className="text-[#75db94]">"document_id"</span>:{" "}
              <span className="text-[#c3c0ff]">"doc_hr_24f9..."</span>,{"\n"}
              {"  "}<span className="text-[#75db94]">"status"</span>:{" "}
              <span className="text-[#c3c0ff]">"uploaded"</span>,{"\n"}
              {"  "}<span className="text-[#75db94]">"queue_status"</span>:{" "}
              <span className="text-[#c3c0ff]">"queued"</span>
              {"\n"}
              {"}"}
            </pre>
            <p className="mt-5 text-xs text-[#636a7f]">
              Usage note: Rudix does not make employment decisions or legal
              determinations. Sensitive data governance remains with your
              organization.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function HRFinalCtaSection({ demoHref }: { demoHref: string }) {
  return (
    <section
      aria-labelledby="hr-cta-title"
      className="relative bg-[#3a35e8] py-28"
    >
      <div className="mx-auto w-full max-w-7xl px-4 text-center lg:px-8">
        <h2
          id="hr-cta-title"
          className="text-4xl font-black text-white lg:text-5xl"
        >
          Turn your HR documents into a policy assistant.
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-[#d8dcff]">
          Reduce repetitive HR queries and give employees consistent,
          source-grounded answers from day one.
        </p>
        <div className="mt-10 flex flex-wrap justify-center gap-4">
          <PublicActionLink
            href={demoHref}
            className="rounded-md bg-white px-8 py-4 text-sm font-semibold text-[#2d2ad1] shadow-[0_10px_30px_rgba(0,0,0,0.25)] transition hover:bg-[#f2f4ff] active:scale-95"
          >
            Speak to us about HR
          </PublicActionLink>
          <PublicActionLink
            href="/solutions"
            className="rounded-md border border-white/70 px-8 py-4 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            View all solutions
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

function HRBreadcrumb() {
  return (
    <nav
      aria-label="Breadcrumb"
      className="mx-auto w-full max-w-7xl px-4 pt-6 lg:px-8"
    >
      <ol className="flex items-center gap-2 text-xs text-[#61677a]">
        <li>
          <PublicActionLink href="/" className="hover:text-[#2a2f40]">
            Home
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#9ca3b8]">/</li>
        <li>
          <PublicActionLink href="/solutions" className="hover:text-[#2a2f40]">
            Solutions
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#9ca3b8]">/</li>
        <li aria-current="page" className="font-semibold text-[#252a3b]">
          HR
        </li>
      </ol>
    </nav>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function HRSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <HRBreadcrumb />
      <HRHeroSection demoHref={links.requestDemo} />
      <HRProblemSection />
      <HRFlowSection />
      <HRDocumentSourcesSection />
      <HRExampleQuestionsSection />
      <HRSecuritySection />
      <HRFinalCtaSection demoHref={links.requestDemo} />
    </>
  );
}
