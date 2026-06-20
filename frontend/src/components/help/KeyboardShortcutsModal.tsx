"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";

import { useOverlayFocus } from "@/lib/use-overlay-focus";

function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad/i.test(navigator.platform);
}

function KeyCombo({ keys }: { keys: string[] }) {
  return (
    <span className="flex items-center gap-1">
      {keys.map((key, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && (
            <span className="text-[10px] text-[#8c87a8]" aria-hidden="true">
              +
            </span>
          )}
          <kbd className="rounded border border-[#d3cff0] bg-[#f7f5ff] px-1.5 py-0.5 text-[11px] font-semibold text-[#3a3659] shadow-sm">
            {key}
          </kbd>
        </span>
      ))}
    </span>
  );
}

type ShortcutRow = {
  id: string;
  labelKey: string;
  keys: string[];
};

type ShortcutGroup = {
  id: string;
  groupKey: string;
  rows: ShortcutRow[];
};

type KeyboardShortcutsModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

export function KeyboardShortcutsModal({
  isOpen,
  onClose,
}: KeyboardShortcutsModalProps) {
  const containerRef = useRef<HTMLElement | null>(null);
  const t = useTranslations("help");

  useOverlayFocus({
    isOpen,
    containerRef,
    onClose,
    autofocusSelector: "[data-overlay-autofocus='true']",
  });

  if (!isOpen) return null;

  const cmdKey = isMacPlatform() ? "⌘" : "Ctrl";

  const groups: ShortcutGroup[] = [
    {
      id: "navigation",
      groupKey: "shortcuts.groups.navigation",
      rows: [
        { id: "search", labelKey: "shortcuts.search", keys: [cmdKey, "K"] },
        {
          id: "shortcuts",
          labelKey: "shortcuts.openShortcuts",
          keys: ["?"],
        },
      ],
    },
    {
      id: "chat",
      groupKey: "shortcuts.groups.chat",
      rows: [
        {
          id: "submit",
          labelKey: "shortcuts.submitMessage",
          keys: [cmdKey, "↵"],
        },
      ],
    },
    {
      id: "overlays",
      groupKey: "shortcuts.groups.overlays",
      rows: [
        { id: "close", labelKey: "shortcuts.closeOverlay", keys: ["Esc"] },
        {
          id: "tab-forward",
          labelKey: "shortcuts.focusNext",
          keys: ["Tab"],
        },
        {
          id: "tab-back",
          labelKey: "shortcuts.focusPrevious",
          keys: ["⇧", "Tab"],
        },
      ],
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <section
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("keyboardShortcutsTitle")}
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#ebe8f7] px-6 py-4">
          <h2 className="text-lg font-bold text-[#2b2745]">
            {t("keyboardShortcutsTitle")}
          </h2>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={onClose}
            aria-label={t("close")}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
          >
            Esc
          </button>
        </div>

        <div className="divide-y divide-[#ebe8f7] px-6 py-2">
          {groups.map((group) => (
            <div key={group.id} className="py-4">
              <p className="mb-3 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
                {t(group.groupKey as Parameters<typeof t>[0])}
              </p>
              <ul className="space-y-2.5">
                {group.rows.map((row) => (
                  <li
                    key={row.id}
                    className="flex items-center justify-between gap-4"
                  >
                    <span className="text-sm text-[#3f3b58]">
                      {t(row.labelKey as Parameters<typeof t>[0])}
                    </span>
                    <KeyCombo keys={row.keys} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
