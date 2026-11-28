import { useTranslations } from "next-intl";

export const RESOURCE_TYPES = [
  "document",
  "collection",
  "connector",
  "connector_source_item",
  "citation",
  "graph_entity",
  "graph_evidence",
  "evaluation",
  "saved_answer",
  "knowledge_card",
  "api_key",
];

export const ACTIONS = [
  "read_only",
  "manage",
  "sync",
  "export",
  "evaluate",
  "cite",
  "search",
];

export function categoryFromPermission(perm: string): string {
  return perm.split(":")[0] ?? perm;
}

export function formatCategory(cat: string): string {
  return cat
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function groupByCategory(
  permissions: string[],
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const p of permissions) {
    const cat = categoryFromPermission(p);
    if (!out[cat]) out[cat] = [];
    out[cat].push(p);
  }
  return out;
}

export function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("adminPermissions");
  const cls =
    status === "active"
      ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
      : status === "revoked"
        ? "bg-red-50 text-red-700 border border-red-100"
        : "bg-amber-50 text-amber-700 border border-amber-100";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}
    >
      {t(`statuses.${status}`)}
    </span>
  );
}

export function PermissionDot({
  has,
  overridden,
}: {
  has: boolean;
  overridden: boolean;
}) {
  const t = useTranslations("adminPermissions");
  if (!has) {
    return (
      <span
        className="inline-block h-4 w-4 rounded-full border border-[#d7d4e8] bg-white"
        title={t("matrix.notGranted")}
        aria-label={t("matrix.notGranted")}
      />
    );
  }
  if (overridden) {
    return (
      <span
        className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-amber-400"
        title={t("matrix.grantedOverridden")}
        aria-label={t("matrix.grantedOverridden")}
      >
        <svg
          className="h-2.5 w-2.5 text-white"
          viewBox="0 0 10 10"
          fill="currentColor"
        >
          <path d="M5 1l1.2 2.4L9 3.9 6.8 6l.5 3L5 7.7 2.7 9l.5-3L1 3.9l2.8-.5z" />
        </svg>
      </span>
    );
  }
  return (
    <span
      className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-[#3525cd]"
      title={t("matrix.granted")}
      aria-label={t("matrix.granted")}
    >
      <svg
        className="h-2.5 w-2.5 text-white"
        viewBox="0 0 10 10"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <path
          d="M2 5l2.5 2.5L8 3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
