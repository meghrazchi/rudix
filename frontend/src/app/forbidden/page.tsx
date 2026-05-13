import Link from "next/link";

type ForbiddenPageProps = {
  searchParams?: Promise<{ from?: string }>;
};

export default async function ForbiddenPage({ searchParams }: ForbiddenPageProps) {
  const resolvedSearchParams = (await searchParams) ?? {};
  const source = resolvedSearchParams.from ? decodeURIComponent(resolvedSearchParams.from) : null;

  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Access Control</p>
        <h1 className="mb-2 text-3xl font-extrabold text-[#2a2640]">Forbidden</h1>
        <p className="mb-5 text-sm text-[#68647b]">
          Your account does not currently have permission to view this route.
        </p>

        {source ? (
          <p className="mb-5 rounded-lg bg-[#f5f3ff] px-3 py-2 text-sm text-[#4d4880]">
            Requested route: <span className="font-semibold">{source}</span>
          </p>
        ) : null}

        <div className="flex flex-wrap gap-3">
          <Link
            href="/dashboard"
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            Go to dashboard
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            Sign in with another account
          </Link>
        </div>
      </main>
    </div>
  );
}
