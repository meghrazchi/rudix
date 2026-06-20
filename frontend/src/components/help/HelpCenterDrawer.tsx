"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useOverlayFocus } from "@/lib/use-overlay-focus";
import { isExternalHref, resolveHelpMenuItems } from "@/lib/top-bar";
import type { HelpTopic } from "@/lib/help-center-context";
import type { AuthenticatedSession } from "@/lib/auth-session";

type Article = {
  id: string;
  topic: HelpTopic;
  title: string;
  description: string;
  href: string;
};

function buildDiagnosticText(session: AuthenticatedSession): string {
  const orgId = (session.organizationId ?? "").slice(0, 8);
  const browser =
    typeof navigator !== "undefined" ? navigator.userAgent.slice(0, 80) : "—";
  return `org:${orgId}… role:${session.role} ua:${browser}`;
}

type HelpCenterDrawerProps = {
  isOpen: boolean;
  onClose: () => void;
  initialTopic?: HelpTopic | null;
  onOpenShortcuts: () => void;
  session: AuthenticatedSession;
};

export function HelpCenterDrawer({
  isOpen,
  onClose,
  initialTopic,
  onOpenShortcuts,
  session,
}: HelpCenterDrawerProps) {
  const containerRef = useRef<HTMLAnchorElement | HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [diagnosticConsent, setDiagnosticConsent] = useState(false);
  const [copied, setCopied] = useState(false);
  const t = useTranslations("help");
  const externalHelpItems = useMemo(() => resolveHelpMenuItems(), []);

  useOverlayFocus({
    isOpen,
    containerRef: containerRef as React.RefObject<HTMLElement | null>,
    onClose,
    autofocusSelector: "[data-overlay-autofocus='true']",
    lockBodyScroll: true,
  });

  const articles: Article[] = useMemo(
    () => [
      {
        id: "upload",
        topic: "upload-documents",
        title: t("articles.upload.title"),
        description: t("articles.upload.description"),
        href: "/documents",
      },
      {
        id: "chat",
        topic: "chat-ask",
        title: t("articles.chat.title"),
        description: t("articles.chat.description"),
        href: "/chat",
      },
      {
        id: "multilingual",
        topic: "multilingual",
        title: t("articles.multilingual.title"),
        description: t("articles.multilingual.description"),
        href: "/user/profile",
      },
      {
        id: "citations",
        topic: "verify-citations",
        title: t("articles.citations.title"),
        description: t("articles.citations.description"),
        href: "/chat",
      },
      {
        id: "collections",
        topic: "manage-collections",
        title: t("articles.collections.title"),
        description: t("articles.collections.description"),
        href: "/collections",
      },
      {
        id: "evaluations",
        topic: "run-evaluations",
        title: t("articles.evaluations.title"),
        description: t("articles.evaluations.description"),
        href: "/evaluations",
      },
      {
        id: "pipeline",
        topic: "rag-pipeline",
        title: t("articles.pipeline.title"),
        description: t("articles.pipeline.description"),
        href: "/rag-pipeline",
      },
      {
        id: "connectors",
        topic: "manage-connectors",
        title: t("articles.connectors.title"),
        description: t("articles.connectors.description"),
        href: "/connectors",
      },
      {
        id: "agents",
        topic: "agent-workspace",
        title: t("articles.agents.title"),
        description: t("articles.agents.description"),
        href: "/workspace/agent",
      },
      {
        id: "users",
        topic: "manage-users",
        title: t("articles.users.title"),
        description: t("articles.users.description"),
        href: "/admin",
      },
    ],
    [t],
  );

  const filtered = useMemo(() => {
    const tokens = query
      .trim()
      .toLowerCase()
      .split(/\s+/)
      .filter((s) => s.length > 0);
    if (tokens.length === 0) return articles;
    return articles.filter((a) =>
      tokens.every(
        (tok) =>
          a.title.toLowerCase().includes(tok) ||
          a.description.toLowerCase().includes(tok),
      ),
    );
  }, [articles, query]);

  async function copyDiagnosticInfo(): Promise<void> {
    const text = buildDiagnosticText(session);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard not available
    }
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-[#17172a]/40" onClick={onClose}>
      <aside
        ref={containerRef as React.RefObject<HTMLElement>}
        role="dialog"
        aria-modal="true"
        aria-label={t("helpCenterTitle")}
        className="absolute top-0 right-0 flex h-full w-full max-w-sm flex-col border-l border-[#d7d4e8] bg-white shadow-2xl sm:max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#ebe8f7] px-5 py-4">
          <h2 className="text-lg font-bold text-[#2b2745]">
            {t("helpCenterTitle")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("close")}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
          >
            Esc
          </button>
        </div>

        {/* Search */}
        <div className="shrink-0 border-b border-[#ebe8f7] px-5 py-3">
          <input
            type="search"
            data-overlay-autofocus="true"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchAriaLabel")}
            className="w-full rounded-lg border border-[#d9d4f0] bg-[#faf9ff] px-3 py-2 text-sm text-[#1f1e2a] placeholder:text-[#7d7896] focus:border-[#6355d5] focus:outline-none"
          />
        </div>

        {/* Articles */}
        <div className="flex-1 overflow-auto px-5 py-4">
          <p className="mb-3 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
            {t("topicsLabel")}
          </p>

          {filtered.length === 0 ? (
            <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
              {t("noArticles")}
            </p>
          ) : (
            <ul className="space-y-2">
              {filtered.map((article) => {
                const highlighted =
                  article.topic === initialTopic && query.trim() === "";
                return (
                  <li key={article.id}>
                    <Link
                      href={article.href}
                      onClick={onClose}
                      className={`block rounded-xl border px-4 py-3 text-left transition hover:bg-[#f5f3ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none ${
                        highlighted
                          ? "border-[#b8b0f5] bg-[#f0eeff]"
                          : "border-[#e8e5f5] bg-[#faf9ff]"
                      }`}
                    >
                      <p className="text-sm font-semibold text-[#2f2a46]">
                        {article.title}
                      </p>
                      <p className="mt-0.5 text-xs text-[#67637d]">
                        {article.description}
                      </p>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}

          {/* Keyboard shortcuts entry */}
          <div className="mt-6 space-y-2 border-t border-[#ebe8f7] pt-4">
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
              {t("resourcesLabel")}
            </p>

            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenShortcuts();
              }}
              className="flex w-full items-center justify-between rounded-xl border border-[#e8e5f5] bg-[#faf9ff] px-4 py-3 text-left transition hover:bg-[#f5f3ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
            >
              <span className="text-sm font-semibold text-[#2f2a46]">
                {t("keyboardShortcutsTitle")}
              </span>
              <kbd className="rounded border border-[#d3cff0] bg-white px-1.5 py-0.5 text-[11px] font-semibold text-[#5d58a8]">
                ?
              </kbd>
            </button>

            {/* External links: docs, support, readme */}
            {externalHelpItems
              .filter((item) => item.id !== "shortcuts")
              .map((item) => {
                const external = isExternalHref(item.href);
                return (
                  <Link
                    key={item.id}
                    href={item.href}
                    onClick={onClose}
                    target={external ? "_blank" : undefined}
                    rel={external ? "noreferrer noopener" : undefined}
                    className="flex items-center justify-between rounded-xl border border-[#e8e5f5] bg-[#faf9ff] px-4 py-3 transition hover:bg-[#f5f3ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                  >
                    <span className="text-sm font-semibold text-[#2f2a46]">
                      {item.label}
                    </span>
                    {external && (
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[16px] text-[#8880b0]"
                      >
                        open_in_new
                      </span>
                    )}
                  </Link>
                );
              })}
          </div>

          {/* Support section with opt-in diagnostic metadata */}
          <div className="mt-6 space-y-2 border-t border-[#ebe8f7] pt-4">
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
              {t("supportLabel")}
            </p>

            <label className="flex cursor-pointer items-center gap-2 text-sm text-[#3f3b58]">
              <input
                type="checkbox"
                checked={diagnosticConsent}
                onChange={(e) => {
                  setDiagnosticConsent(e.target.checked);
                  setCopied(false);
                }}
                className="rounded border-[#c4bfdf] text-[#3525cd] focus:ring-[#3525cd]"
              />
              {t("includeDiagnosticInfo")}
            </label>

            {diagnosticConsent && (
              <div className="rounded-lg border border-[#e4e1f2] bg-[#f7f5ff] px-3 py-2">
                <p className="mb-1.5 text-[11px] text-[#7a7594]">
                  {t("diagnosticInfoNote")}
                </p>
                <code className="block font-mono text-[11px] break-all text-[#4a456b]">
                  {buildDiagnosticText(session)}
                </code>
                <button
                  type="button"
                  onClick={() => void copyDiagnosticInfo()}
                  className="mt-2 rounded border border-[#d3cff0] bg-white px-2 py-1 text-[11px] font-semibold text-[#5d58a8] hover:bg-[#f0eeff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                >
                  {copied ? t("copied") : t("copyDiagnosticInfo")}
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
