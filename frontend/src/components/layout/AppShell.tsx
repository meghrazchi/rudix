import Link from "next/link";
import type { ReactNode } from "react";

type NavItem = {
  href: string;
  label: string;
};

type AppShellProps = {
  title: string;
  badge?: string;
  activeHref: string;
  children: ReactNode;
};

const navItems: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/documents", label: "Documents" },
  { href: "/chat", label: "Chat" },
  { href: "/evaluations", label: "Evaluations" },
  { href: "/rag-pipeline", label: "Pipeline Explorer" },
  { href: "/settings", label: "Settings" },
  { href: "/admin", label: "Admin" },
];

export function AppShell({ title, badge, activeHref, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-[#f5f4ff] text-[#1b1b24]" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
      <div className="mx-auto flex min-h-screen w-full max-w-[1600px] flex-col lg:flex-row">
        <aside className="border-b border-[#d7d4e7] bg-[#f7f5ff] px-4 py-4 lg:w-64 lg:border-b-0 lg:border-r lg:px-5 lg:py-8">
          <div className="mb-6">
            <h1 className="text-2xl font-extrabold text-[#3525cd]">Rudix</h1>
            <p className="text-sm font-semibold text-[#5e5b72]">Enterprise RAG</p>
          </div>
          <nav className="grid gap-1">
            {navItems.map((item) => {
              const active = item.href === activeHref;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={
                    active
                      ? "rounded-lg border-l-4 border-[#3525cd] bg-[#ece8ff] px-3 py-2 text-sm font-bold text-[#3525cd]"
                      : "rounded-lg px-3 py-2 text-sm font-semibold text-[#56536a] transition hover:bg-[#eceaf8]"
                  }
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-[#d7d4e7] bg-white px-4 py-4 lg:px-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-semibold text-[#3525cd] lg:text-2xl">{title}</h2>
                {badge ? (
                  <span className="rounded bg-[#d6e4ff] px-2 py-1 text-xs font-semibold uppercase tracking-wide text-[#38485d]">
                    {badge}
                  </span>
                ) : null}
              </div>
              <div className="text-xs font-medium text-[#6b6880]">Page 1 of frontend rollout</div>
            </div>
          </header>
          <main className="min-h-0 flex-1">{children}</main>
        </div>
      </div>
    </div>
  );
}
