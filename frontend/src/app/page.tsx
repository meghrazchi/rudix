import Link from "next/link";

const plannedPages = [
  { href: "/rag-pipeline", label: "Page 1: Pipeline Explorer", status: "ready" },
  { href: null, label: "Page 2: Dashboard", status: "next" },
  { href: null, label: "Page 3: Documents", status: "next" },
  { href: null, label: "Page 4: Chat", status: "next" },
] as const;

export default function Home() {
  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f3f1ff] px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-3xl rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Frontend Rollout</p>
        <h1 className="mb-3 text-3xl font-extrabold text-[#2a2640]">Design-based pages delivered one by one</h1>
        <p className="mb-6 text-sm text-[#68647b]">
          First page is implemented from the pipeline design. Remaining pages are queued for the next iterations.
        </p>

        <div className="space-y-3">
          {plannedPages.map((page) =>
            page.href ? (
              <Link
                key={page.label}
                href={page.href}
                className="flex items-center justify-between rounded-xl border border-[#dfdbee] px-4 py-3 transition hover:border-[#aba3d8] hover:bg-[#f7f4ff]"
              >
                <span className="font-semibold text-[#2c2943]">{page.label}</span>
                <span
                  className={`rounded px-2 py-1 text-xs font-bold uppercase tracking-wide ${
                    page.status === "ready"
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-[#ece8ff] text-[#5d57a4]"
                  }`}
                >
                  {page.status === "ready" ? "ready" : "planned"}
                </span>
              </Link>
            ) : (
              <div
                key={page.label}
                className="flex items-center justify-between rounded-xl border border-[#efedf6] bg-[#faf9ff] px-4 py-3"
              >
                <span className="font-semibold text-[#7a768f]">{page.label}</span>
                <span className="rounded bg-[#ece8ff] px-2 py-1 text-xs font-bold uppercase tracking-wide text-[#5d57a4]">
                  planned
                </span>
              </div>
            ),
          )}
        </div>
      </main>
    </div>
  );
}
