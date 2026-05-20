import Link from "next/link";

type FeaturePlaceholderProps = {
  title: string;
  summary: string;
  hints: string[];
};

export function FeaturePlaceholder({
  title,
  summary,
  hints,
}: FeaturePlaceholderProps) {
  return (
    <div className="px-4 py-6 lg:px-8 lg:py-8">
      <section className="mb-6 rounded-2xl border border-[#d8d5e8] bg-white p-6">
        <p className="mb-2 text-xs font-bold tracking-[0.15em] text-[#5d58a8] uppercase">
          Rudix Product Surface
        </p>
        <h2 className="mb-2 text-2xl font-bold text-[#2c2943]">{title}</h2>
        <p className="text-sm text-[#66627a]">{summary}</p>
      </section>

      <section className="rounded-2xl border border-[#d8d5e8] bg-white p-6">
        <h3 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          Foundational Behaviors
        </h3>
        <ul className="space-y-2 text-sm text-[#4f4b63]">
          {hints.map((hint) => (
            <li key={hint} className="rounded-lg bg-[#f8f6ff] px-3 py-2">
              {hint}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-[#66627a]">
          Need the current pipeline implementation? Open{" "}
          <Link
            href="/rag-pipeline"
            className="font-semibold text-[#3525cd] underline decoration-[#bbb5e5]"
          >
            Pipeline Explorer
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
