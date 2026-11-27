export type TrustLevel = "high" | "medium" | "low" | "warning" | "not_found";

export function trustLevelBadge(level: TrustLevel): {
  label: string;
  cls: string;
  icon: string;
} {
  if (level === "high")
    return {
      label: "High",
      icon: "check_circle",
      cls: "inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-800",
    };
  if (level === "medium")
    return {
      label: "Medium",
      icon: "check_circle",
      cls: "inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-800",
    };
  if (level === "warning")
    return {
      label: "Warning",
      icon: "warning",
      cls: "inline-flex items-center gap-1 rounded-full border border-orange-200 bg-orange-50 px-2 py-0.5 text-[10px] font-bold uppercase text-orange-800",
    };
  if (level === "not_found")
    return {
      label: "Not Found",
      icon: "search_off",
      cls: "inline-flex items-center gap-1 rounded-full border border-[#e0dced] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-bold uppercase text-[#6a6780]",
    };
  return {
    label: "Low",
    icon: "error",
    cls: "inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-800",
  };
}

export function trustStatusBadge(
  status: string | null | undefined,
): { label: string; cls: string } | null {
  if (!status || status === "uploaded") return null;
  if (status === "trusted")
    return {
      label: "Trusted",
      cls: "rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  if (status === "stale")
    return {
      label: "Stale",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (status === "revoked" || status === "deleted")
    return {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  return {
    label: status.charAt(0).toUpperCase() + status.slice(1),
    cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
  };
}

export function ocrBadge(
  quality: string | null | undefined,
  warn: boolean | undefined,
): { label: string; cls: string } | null {
  if (!warn && (!quality || quality === "high" || quality === "not_required"))
    return null;
  if (quality === "low" || quality === "failed" || warn)
    return {
      label: "OCR low confidence",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (quality === "medium")
    return {
      label: "OCR medium",
      cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
    };
  return null;
}

export function tableExtractionBadge(
  warn: boolean | undefined,
): { label: string; cls: string } | null {
  if (!warn) return null;
  return {
    label: "Table low confidence",
    cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
  };
}

export function extractionQualityBadge(
  quality: string | null | undefined,
  warn: boolean | undefined,
): { label: string; cls: string } | null {
  if (!warn) return null;
  const label =
    quality === "corrupted"
      ? "Corrupted"
      : quality === "unsupported"
        ? "Unsupported format"
        : quality === "encrypted"
          ? "Encrypted"
          : "Extraction issue";
  return {
    label,
    cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
  };
}

export function processingWarningBadge(
  warn: boolean | undefined,
): { label: string; cls: string } | null {
  if (!warn) return null;
  return {
    label: "Processing incomplete",
    cls: "rounded-full border border-orange-200 bg-orange-50 px-1.5 py-0.5 text-[9px] font-semibold text-orange-800 uppercase",
  };
}

export function answerModeBadge(
  mode: "grounded" | "guidance" | null | undefined,
): { label: string; cls: string; icon: string } | null {
  if (mode === "guidance")
    return {
      label: "General product guidance",
      icon: "tips_and_updates",
      cls: "inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-bold uppercase text-sky-800",
    };
  return null;
}

export function freshnessBadge(
  state: string | null | undefined,
  staleWarn: boolean | undefined,
  expiredWarn: boolean | undefined,
  unreviewedWarn: boolean | undefined,
  deprecatedWarn: boolean | undefined,
): { label: string; cls: string } | null {
  const effective =
    state ??
    (expiredWarn
      ? "expired"
      : staleWarn
        ? "stale"
        : unreviewedWarn
          ? "unreviewed"
          : deprecatedWarn
            ? "deprecated"
            : null);
  if (!effective || effective === "current" || effective === "unknown")
    return null;
  if (effective === "stale")
    return {
      label: "Stale",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (effective === "expired")
    return {
      label: "Expired",
      cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  if (effective === "deprecated")
    return {
      label: "Deprecated",
      cls: "rounded-full border border-orange-200 bg-orange-50 px-1.5 py-0.5 text-[9px] font-semibold text-orange-800 uppercase",
    };
  if (effective === "draft")
    return {
      label: "Draft",
      cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
    };
  if (effective === "unreviewed")
    return {
      label: "Unreviewed",
      cls: "rounded-full border border-yellow-200 bg-yellow-50 px-1.5 py-0.5 text-[9px] font-semibold text-yellow-800 uppercase",
    };
  return null;
}

export function conflictBadge(
  status: "preferred" | "conflicting" | "neutral" | null | undefined,
): { label: string; cls: string } | null {
  if (status === "preferred")
    return {
      label: "Preferred",
      cls: "rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  if (status === "conflicting")
    return {
      label: "Conflicting",
      cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  return null;
}

export function claimSupportBadge(
  status: "supported" | "partially_supported" | "unsupported" | "unverifiable",
): { label: string; cls: string } {
  if (status === "supported")
    return {
      label: "Supported",
      cls: "rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  if (status === "partially_supported")
    return {
      label: "Partial",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (status === "unverifiable")
    return {
      label: "Unverifiable",
      cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
    };
  return {
    label: "Unsupported",
    cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
  };
}
