"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

import { useOverlayFocus } from "@/lib/use-overlay-focus";
import type { ConsentDecisions } from "@/lib/consent";

type CategoryRowProps = {
  id: string;
  title: string;
  description: string;
  required?: boolean;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

function CategoryRow({
  id,
  title,
  description,
  required = false,
  checked,
  onChange,
}: CategoryRowProps) {
  const toggleId = `consent-toggle-${id}`;

  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-[#e8e6f5] bg-[#f9f8ff] p-4">
      <div className="min-w-0 flex-1">
        <label
          htmlFor={toggleId}
          className="flex items-center gap-2 text-sm font-semibold text-[#29263f]"
        >
          {title}
          {required && (
            <span className="inline-flex items-center rounded-full bg-[#e8e6f5] px-2 py-0.5 text-[11px] font-medium text-[#5d58a8]">
              Always on
            </span>
          )}
        </label>
        <p className="mt-1 text-sm text-[#5f5b76]">{description}</p>
      </div>
      <div className="shrink-0 pt-0.5">
        <button
          type="button"
          id={toggleId}
          role="switch"
          aria-checked={checked}
          disabled={required}
          onClick={() => onChange(!checked)}
          className={[
            "relative inline-flex h-6 w-10 cursor-pointer items-center rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]",
            checked ? "bg-[#5d58a8]" : "bg-[#c7c4e0]",
            required ? "cursor-not-allowed opacity-60" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <span
            className={[
              "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
              checked ? "translate-x-5" : "translate-x-1",
            ].join(" ")}
          />
        </button>
      </div>
    </div>
  );
}

type CookiePreferencesModalProps = {
  isOpen: boolean;
  decisions: ConsentDecisions;
  onClose: () => void;
  onAcceptAll: () => void;
  onRejectNonEssential: () => void;
  onSave: (partial: Partial<ConsentDecisions>) => void;
};

export function CookiePreferencesModal({
  isOpen,
  decisions,
  onClose,
  onAcceptAll,
  onRejectNonEssential,
  onSave,
}: CookiePreferencesModalProps) {
  const t = useTranslations("cookieConsent");
  const containerRef = useRef<HTMLElement | null>(null);

  const [localDecisions, setLocalDecisions] =
    useState<ConsentDecisions>(decisions);

  useOverlayFocus({
    isOpen,
    containerRef,
    onClose,
    autofocusSelector: "[data-overlay-autofocus='true']",
    lockBodyScroll: true,
  });

  if (!isOpen) return null;

  function handleSave() {
    onSave(localDecisions);
  }

  const gaId = process.env.NEXT_PUBLIC_GA_ID;
  const analyticsConfigured = Boolean(gaId && gaId.trim().length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/40"
        aria-hidden="true"
        onClick={onClose}
      />
      <section
        ref={containerRef as React.RefObject<HTMLElement>}
        role="dialog"
        aria-modal="true"
        aria-labelledby="consent-modal-title"
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl border border-[#dad8ef] bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-[#e8e6f5] px-6 py-4">
          <h2
            id="consent-modal-title"
            className="text-base font-semibold text-[#29263f]"
          >
            {t("preferencesTitle")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            data-overlay-autofocus="true"
            aria-label={t("close")}
            className="rounded-md p-1 text-[#8c87a8] hover:bg-[#f5f4ff] hover:text-[#29263f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-3 overflow-y-auto px-6 py-4" style={{ maxHeight: "60vh" }}>
          <p className="text-sm text-[#5f5b76]">
            {t("preferencesDescription")}{" "}
            <Link
              href="/legal/cookies"
              className="font-medium text-[#5d58a8] underline underline-offset-2 hover:text-[#3f3b8a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
            >
              {t("cookiePolicyLink")}
            </Link>
          </p>

          <CategoryRow
            id="necessary"
            title={t("categories.necessary.title")}
            description={t("categories.necessary.description")}
            required
            checked
            onChange={() => {}}
          />

          <CategoryRow
            id="functional"
            title={t("categories.functional.title")}
            description={t("categories.functional.description")}
            checked={localDecisions.functional}
            onChange={(checked) =>
              setLocalDecisions((d) => ({ ...d, functional: checked }))
            }
          />

          {analyticsConfigured && (
            <CategoryRow
              id="analytics"
              title={t("categories.analytics.title")}
              description={t("categories.analytics.description")}
              checked={localDecisions.analytics}
              onChange={(checked) =>
                setLocalDecisions((d) => ({ ...d, analytics: checked }))
              }
            />
          )}
        </div>

        <div className="flex flex-col gap-2 border-t border-[#e8e6f5] px-6 py-4 sm:flex-row sm:justify-between">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onRejectNonEssential}
              className="rounded-lg border border-[#c7c4e0] bg-white px-3.5 py-2 text-sm font-medium text-[#29263f] hover:bg-[#f5f4ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
            >
              {t("rejectNonEssential")}
            </button>
            <button
              type="button"
              onClick={onAcceptAll}
              className="rounded-lg border border-[#c7c4e0] bg-white px-3.5 py-2 text-sm font-medium text-[#29263f] hover:bg-[#f5f4ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
            >
              {t("acceptAll")}
            </button>
          </div>
          <button
            type="button"
            onClick={handleSave}
            className="rounded-lg bg-[#5d58a8] px-3.5 py-2 text-sm font-medium text-white hover:bg-[#4a469a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
          >
            {t("savePreferences")}
          </button>
        </div>
      </section>
    </div>
  );
}
