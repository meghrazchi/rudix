type LegalSection = {
  heading: string;
  body: React.ReactNode;
};

type LegalPageLayoutProps = {
  title: string;
  version: string;
  effectiveDate: string;
  sections: LegalSection[];
};

export function LegalPageLayout({
  title,
  version,
  effectiveDate,
  sections,
}: LegalPageLayoutProps) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 lg:px-8">
      <div
        role="note"
        aria-label="Legal review notice"
        className="mb-8 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        <strong>Note:</strong> This document contains placeholder copy pending
        formal legal review. It should not be considered final legal advice or a
        binding agreement until approved by legal counsel.
      </div>

      <h1 className="text-3xl font-bold tracking-tight text-[#11131a]">
        {title}
      </h1>
      <p className="mt-2 text-sm text-[#7c8194]">
        Version {version} &middot; Effective {effectiveDate}
      </p>

      <div className="mt-10 space-y-10">
        {sections.map((section) => (
          <section key={section.heading} aria-label={section.heading}>
            <h2 className="text-lg font-semibold text-[#25283a]">
              {section.heading}
            </h2>
            <div className="mt-3 space-y-3 text-sm leading-7 text-[#4b4f60]">
              {section.body}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
