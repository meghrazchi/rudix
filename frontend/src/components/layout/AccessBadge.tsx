type AccessBadgeType =
  | "owner"
  | "admin"
  | "assigned"
  | "collection-granted"
  | "connector-acl"
  | "inherited"
  | "read-only"
  | "denied";

type AccessBadgeProps = {
  type: AccessBadgeType;
  label?: string;
};

const BADGE_STYLES: Record<
  AccessBadgeType,
  { className: string; defaultLabel: string }
> = {
  owner: {
    className: "bg-violet-100 text-violet-800 border-violet-200",
    defaultLabel: "Owner",
  },
  admin: {
    className: "bg-indigo-100 text-indigo-800 border-indigo-200",
    defaultLabel: "Admin",
  },
  assigned: {
    className: "bg-emerald-100 text-emerald-800 border-emerald-200",
    defaultLabel: "Assigned",
  },
  "collection-granted": {
    className: "bg-sky-100 text-sky-800 border-sky-200",
    defaultLabel: "Collection",
  },
  "connector-acl": {
    className: "bg-cyan-100 text-cyan-800 border-cyan-200",
    defaultLabel: "Connector ACL",
  },
  inherited: {
    className: "bg-slate-100 text-slate-700 border-slate-200",
    defaultLabel: "Inherited",
  },
  "read-only": {
    className: "bg-amber-100 text-amber-800 border-amber-200",
    defaultLabel: "Read only",
  },
  denied: {
    className: "bg-rose-100 text-rose-700 border-rose-200",
    defaultLabel: "No access",
  },
};

export function AccessBadge({ type, label }: AccessBadgeProps) {
  const { className, defaultLabel } = BADGE_STYLES[type];
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${className}`}
      aria-label={`Access: ${label ?? defaultLabel}`}
    >
      {label ?? defaultLabel}
    </span>
  );
}

type PermissionDeniedBadgeProps = {
  reason?: string;
};

// Compact inline badge for permission-denied states inside tables, lists, etc.
export function PermissionDeniedBadge({ reason }: PermissionDeniedBadgeProps) {
  return (
    <AccessBadge
      type="denied"
      label={reason ?? "No access"}
    />
  );
}

type ReadOnlyBadgeProps = {
  label?: string;
};

export function ReadOnlyBadge({ label }: ReadOnlyBadgeProps) {
  return <AccessBadge type="read-only" label={label} />;
}
