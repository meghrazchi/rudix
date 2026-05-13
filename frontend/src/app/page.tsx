import Link from "next/link";

const productRoutes = [
  { href: "/dashboard", label: "Dashboard", note: "Protected" },
  { href: "/documents", label: "Documents", note: "Protected" },
  { href: "/chat", label: "Chat", note: "Protected" },
  { href: "/evaluations", label: "Evaluations", note: "Protected" },
  { href: "/rag-pipeline", label: "Pipeline Explorer", note: "Protected" },
  { href: "/settings", label: "Settings", note: "Protected" },
  { href: "/admin", label: "Admin", note: "Owner/Admin only" },
] as const;

export default function Home() {
  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-3xl rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Frontend</p>
        <h1 className="mb-3 text-3xl font-extrabold text-[#2a2640]">Application shell and protected routes</h1>
        <p className="mb-6 text-sm text-[#68647b]">
          Use login to create a local session. Product pages run behind route protection and role-aware navigation.
        </p>

        <div className="mb-6 flex flex-wrap gap-3">
          <Link
            href="/login"
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            Login
          </Link>
          <Link
            href="/dashboard"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            Open dashboard
          </Link>
        </div>

        <div className="space-y-3">
          {productRoutes.map((route) => (
            <Link
              key={route.href}
              href={route.href}
              className="flex items-center justify-between rounded-xl border border-[#dfdbee] px-4 py-3 transition hover:border-[#aba3d8] hover:bg-[#f7f4ff]"
            >
              <span className="font-semibold text-[#2c2943]">{route.label}</span>
              <span className="rounded bg-[#ece8ff] px-2 py-1 text-xs font-bold uppercase tracking-wide text-[#5d57a4]">
                {route.note}
              </span>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
