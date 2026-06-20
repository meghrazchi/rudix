"use client";

import { useTranslations } from "next-intl";

import { useHelpCenter, type HelpTopic } from "@/lib/help-center-context";

type ContextualHelpLinkProps = {
  topic: HelpTopic;
  className?: string;
};

export function ContextualHelpLink({
  topic,
  className = "",
}: ContextualHelpLinkProps) {
  const { openHelpCenter } = useHelpCenter();
  const t = useTranslations("help");

  return (
    <button
      type="button"
      onClick={() => openHelpCenter(topic)}
      aria-label={t("openHelpForTopic")}
      title={t("openHelpForTopic")}
      className={`inline-flex h-5 w-5 items-center justify-center rounded-full border border-[#d3cff0] bg-[#f7f5ff] text-[#7370a0] transition hover:bg-[#eceaff] hover:text-[#3525cd] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none ${className}`}
    >
      <span
        aria-hidden="true"
        className="material-symbols-outlined text-[14px]"
      >
        help
      </span>
    </button>
  );
}
