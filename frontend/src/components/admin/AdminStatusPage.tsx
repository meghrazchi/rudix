"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  addIncidentNote,
  createIncident,
  getIncident,
  getStatusSnapshot,
  listIncidents,
  updateIncident,
  type AddIncidentNoteRequest,
  type CreateIncidentRequest,
  type IncidentDetail,
  type IncidentSeverity,
  type IncidentStatus,
  type IncidentSummary,
  type IncidentsQuery,
  type UpdateIncidentRequest,
} from "@/lib/api/incidents";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-rose-100 text-rose-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-sky-100 text-sky-800",
};

const STATUS_BADGE: Record<string, string> = {
  investigating: "bg-rose-100 text-rose-800",
  identified: "bg-amber-100 text-amber-800",
  monitoring: "bg-sky-100 text-sky-800",
  resolved: "bg-emerald-100 text-emerald-800",
};

const STATUS_OPTIONS: { value: IncidentStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "investigating", label: "Investigating" },
  { value: "identified", label: "Identified" },
  { value: "monitoring", label: "Monitoring" },
  { value: "resolved", label: "Resolved" },
];

const SEVERITY_OPTIONS: { value: IncidentSeverity | ""; label: string }[] = [
  { value: "", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

function Badge({
  label,
  className,
}: {
  label: string;
  className: string;
}) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${className}`}
    >
      {label}
    </span>
  );
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {message}
    </p>
  );
}

function DrawerRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
      <dt className="shrink-0 text-sm text-[#4f4b68]">{label}</dt>
      <dd className="text-right text-sm text-[#2f2a46]">{children}</dd>
    </div>
  );
}

function IncidentDrawer({
  incidentId,
  onClose,
}: {
  incidentId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [noteText, setNoteText] = useState("");
  const [noteStatus, setNoteStatus] = useState<IncidentStatus | "">("");
  const [updateStatus, setUpdateStatus] = useState<IncidentStatus | "">("");
  const [updateSeverity, setUpdateSeverity] = useState<IncidentSeverity | "">("");

  const detailQuery = useQuery({
    queryKey: queryKeys.admin.incidentDetail(incidentId),
    queryFn: () => getIncident(incidentId),
  });

  const noteMutation = useMutation({
    mutationFn: (req: AddIncidentNoteRequest) =>
      addIncidentNote(incidentId, req),
    onSuccess: () => {
      setNoteText("");
      setNoteStatus("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.incidentDetail(incidentId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.incidents(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.statusSnapshot,
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (req: UpdateIncidentRequest) => updateIncident(incidentId, req),
    onSuccess: () => {
      setUpdateStatus("");
      setUpdateSeverity("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.incidentDetail(incidentId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.incidents(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.statusSnapshot,
      });
    },
  });

  const incident = detailQuery.data;
  const isBusy = noteMutation.isPending || updateMutation.isPending;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Incident detail"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close drawer"
      />
      <aside className="relative z-50 flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-[#e4e1f2] px-5 py-4">
          <h2 className="text-lg font-bold text-[#2a2640]">Incident detail</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#6d6985] hover:bg-[#f5f3ff] hover:text-[#2a2640]"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {detailQuery.isLoading ? (
          <LoadingState compact title="Loading…" className="p-8" />
        ) : detailQuery.isError ? (
          <div className="p-5">
            <ErrorState
              compact
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
              onRetry={() => void detailQuery.refetch()}
            />
          </div>
        ) : incident ? (
          <div className="flex flex-1 flex-col gap-5 p-5">
            <section className="space-y-1">
              <p className="text-base font-semibold text-[#2a2640]">
                {incident.title}
              </p>
              <dl className="mt-2 space-y-1">
                <DrawerRow label="Status">
                  <Badge
                    label={incident.status}
                    className={STATUS_BADGE[incident.status] ?? "bg-slate-100 text-slate-600"}
                  />
                </DrawerRow>
                <DrawerRow label="Severity">
                  <Badge
                    label={incident.severity}
                    className={SEVERITY_BADGE[incident.severity] ?? "bg-slate-100 text-slate-600"}
                  />
                </DrawerRow>
                <DrawerRow label="Public banner">
                  {incident.is_public ? "Yes" : "No"}
                </DrawerRow>
                <DrawerRow label="Started">
                  {formatDateTime(incident.started_at)}
                </DrawerRow>
                {incident.resolved_at ? (
                  <DrawerRow label="Resolved">
                    {formatDateTime(incident.resolved_at)}
                  </DrawerRow>
                ) : null}
                {incident.affected_services.length > 0 ? (
                  <DrawerRow label="Affected services">
                    <span className="text-right">
                      {incident.affected_services.join(", ")}
                    </span>
                  </DrawerRow>
                ) : null}
              </dl>
              {incident.message ? (
                <p className="mt-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#4f4b68]">
                  {incident.message}
                </p>
              ) : null}
            </section>

            <section className="space-y-2">
              <p className="text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                Quick update
              </p>
              <div className="flex flex-wrap gap-2">
                <select
                  value={updateStatus}
                  onChange={(e) =>
                    setUpdateStatus(e.target.value as IncidentStatus | "")
                  }
                  className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
                  aria-label="Change status"
                >
                  <option value="">Change status…</option>
                  {STATUS_OPTIONS.filter((o) => o.value !== "").map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <select
                  value={updateSeverity}
                  onChange={(e) =>
                    setUpdateSeverity(e.target.value as IncidentSeverity | "")
                  }
                  className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
                  aria-label="Change severity"
                >
                  <option value="">Change severity…</option>
                  {SEVERITY_OPTIONS.filter((o) => o.value !== "").map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={
                    isBusy || (!updateStatus && !updateSeverity)
                  }
                  onClick={() => {
                    const req: UpdateIncidentRequest = {};
                    if (updateStatus) req.status = updateStatus;
                    if (updateSeverity) req.severity = updateSeverity;
                    updateMutation.mutate(req);
                  }}
                  className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {updateMutation.isPending ? "Saving…" : "Apply"}
                </button>
              </div>
              {updateMutation.isError ? (
                <ErrorNotice
                  message={getApiErrorMessage(updateMutation.error)}
                />
              ) : null}
            </section>

            <section className="space-y-2">
              <p className="text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                Add note
              </p>
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                rows={3}
                placeholder="Describe what's happening or an update…"
                className="w-full rounded-lg border border-[#cbc5e6] px-3 py-2 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
                aria-label="Note text"
              />
              <div className="flex items-center gap-2">
                <select
                  value={noteStatus}
                  onChange={(e) =>
                    setNoteStatus(e.target.value as IncidentStatus | "")
                  }
                  className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
                  aria-label="Optionally update status with note"
                >
                  <option value="">No status change</option>
                  {STATUS_OPTIONS.filter((o) => o.value !== "").map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={isBusy || !noteText.trim()}
                  onClick={() =>
                    noteMutation.mutate({
                      note: noteText.trim(),
                      ...(noteStatus ? { status_change: noteStatus } : {}),
                    })
                  }
                  className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {noteMutation.isPending ? "Posting…" : "Post note"}
                </button>
              </div>
              {noteMutation.isError ? (
                <ErrorNotice
                  message={getApiErrorMessage(noteMutation.error)}
                />
              ) : null}
            </section>

            {incident.notes.length > 0 ? (
              <section>
                <p className="mb-2 text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                  Notes timeline
                </p>
                <ul className="space-y-1">
                  {incident.notes.map((n) => (
                    <li
                      key={n.id}
                      className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs"
                    >
                      {n.status_change ? (
                        <Badge
                          label={n.status_change}
                          className={
                            STATUS_BADGE[n.status_change] ??
                            "bg-slate-100 text-slate-600"
                          }
                        />
                      ) : null}
                      <p className="mt-1 text-[#2f2a46]">{n.note}</p>
                      <p className="mt-0.5 text-[#8d8aa3]">
                        {formatDateTime(n.created_at)}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        ) : null}
      </aside>
    </div>
  );
}

function CreateIncidentModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<IncidentSeverity>("medium");
  const [message, setMessage] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [services, setServices] = useState("");

  const createMutation = useMutation({
    mutationFn: (req: CreateIncidentRequest) => createIncident(req),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.incidents(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.statusSnapshot,
      });
      onCreated();
    },
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Create incident"
    >
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl">
        <h2 className="mb-4 text-lg font-bold text-[#2a2640]">
          New incident
        </h2>
        <div className="space-y-3">
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Title *
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Brief description of the issue"
              className="rounded-lg border border-[#cbc5e6] px-3 py-2 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Severity
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
              className="rounded-lg border border-[#cbc5e6] px-3 py-2 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {SEVERITY_OPTIONS.filter((o) => o.value !== "").map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Affected services (comma-separated)
            <input
              value={services}
              onChange={(e) => setServices(e.target.value)}
              placeholder="e.g. chat, search, indexing"
              className="rounded-lg border border-[#cbc5e6] px-3 py-2 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Message (optional)
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={2}
              placeholder="User-visible message"
              className="rounded-lg border border-[#cbc5e6] px-3 py-2 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
          <label className="flex items-center gap-2 text-sm font-semibold text-[#4f4b68]">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="accent-[#3525cd]"
            />
            Show as in-app banner to users
          </label>
        </div>
        {createMutation.isError ? (
          <div className="mt-3">
            <ErrorNotice message={getApiErrorMessage(createMutation.error)} />
          </div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[#cbc5e6] px-4 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={createMutation.isPending || !title.trim()}
            onClick={() =>
              createMutation.mutate({
                title: title.trim(),
                severity,
                affected_services: services
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
                message: message.trim() || null,
                is_public: isPublic,
              })
            }
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {createMutation.isPending ? "Creating…" : "Create incident"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SnapshotSummary() {
  const snapshotQuery = useQuery({
    queryKey: queryKeys.admin.statusSnapshot,
    queryFn: getStatusSnapshot,
    refetchInterval: 60_000,
  });

  if (snapshotQuery.isLoading) {
    return (
      <LoadingState compact title="Loading status…" className="px-5 py-4" />
    );
  }
  if (snapshotQuery.isError) return null;

  const snap = snapshotQuery.data;
  if (!snap) return null;

  const overallOk =
    snap.active_incidents.length === 0 && snap.open_failed_job_count === 0;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <MetricCard
        label="Overall"
        value={overallOk ? "Operational" : "Degraded"}
        className={
          overallOk
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-rose-200 bg-rose-50 text-rose-800"
        }
      />
      <MetricCard
        label="Active incidents"
        value={String(snap.active_incidents.length)}
        className={
          snap.active_incidents.length === 0
            ? "border-[#e4e1f2] bg-[#faf9ff] text-[#3525cd]"
            : "border-rose-200 bg-rose-50 text-rose-800"
        }
      />
      <MetricCard
        label="Resolved (24 h)"
        value={String(snap.recently_resolved.length)}
        className="border-[#e4e1f2] bg-[#faf9ff] text-[#3525cd]"
      />
      <MetricCard
        label="Open failed jobs"
        value={String(snap.open_failed_job_count)}
        className={
          snap.open_failed_job_count === 0
            ? "border-[#e4e1f2] bg-[#faf9ff] text-[#3525cd]"
            : "border-amber-200 bg-amber-50 text-amber-800"
        }
      />
    </div>
  );
}

function MetricCard({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className: string;
}) {
  return (
    <div
      className={`rounded-xl border px-4 py-3 text-center ${className}`}
    >
      <p className="text-xs font-semibold tracking-wide uppercase">{label}</p>
      <p className="mt-1 text-2xl font-extrabold">{value}</p>
    </div>
  );
}

function IncidentRow({
  incident,
  onOpen,
}: {
  incident: IncidentSummary;
  onOpen: () => void;
}) {
  return (
    <tr className="border-b border-[#e4e1f2] hover:bg-[#faf9ff]">
      <td className="px-3 py-2">
        <Badge
          label={incident.status}
          className={STATUS_BADGE[incident.status] ?? "bg-slate-100 text-slate-600"}
        />
      </td>
      <td className="px-3 py-2">
        <Badge
          label={incident.severity}
          className={SEVERITY_BADGE[incident.severity] ?? "bg-slate-100 text-slate-600"}
        />
      </td>
      <td className="px-3 py-2 text-sm font-medium text-[#2f2a46]">
        {incident.title}
      </td>
      <td className="px-3 py-2 text-sm text-[#6d6985]">
        {incident.affected_services.join(", ") || "—"}
      </td>
      <td className="px-3 py-2 text-sm text-[#6d6985]">
        {formatDateTime(incident.started_at)}
      </td>
      <td className="px-3 py-2 text-center">
        <span
          className={`inline-block h-2 w-2 rounded-full ${incident.is_public ? "bg-emerald-500" : "bg-slate-300"}`}
          title={incident.is_public ? "Public banner active" : "Not shown to users"}
        />
      </td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={onOpen}
          className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
        >
          View
        </button>
      </td>
    </tr>
  );
}

export function AdminStatusPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<IncidentStatus | "">("");
  const [severityFilter, setSeverityFilter] = useState<IncidentSeverity | "">("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [openIncidentId, setOpenIncidentId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const query: IncidentsQuery = {
    page,
    page_size: 25,
    ...(activeOnly ? { active_only: true } : {}),
    ...(!activeOnly && statusFilter ? { status: statusFilter } : {}),
    ...(severityFilter ? { severity: severityFilter } : {}),
  };

  const listQuery = useQuery({
    queryKey: queryKeys.admin.incidents(query as Record<string, unknown>),
    queryFn: () => listIncidents(query),
    enabled: isAdminUser,
  });

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin access restricted"
          description="Only owner and admin roles can access the status page."
          compact={false}
        />
      </section>
    );
  }

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 25));

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      {openIncidentId ? (
        <IncidentDrawer
          incidentId={openIncidentId}
          onClose={() => setOpenIncidentId(null)}
        />
      ) : null}
      {showCreate ? (
        <CreateIncidentModal
          onClose={() => setShowCreate(false)}
          onCreated={() => setShowCreate(false)}
        />
      ) : null}

      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Rudix Admin
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              System status
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Active incidents, service health, and maintenance windows.
              Mark incidents as public to show in-app banners to users.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void listQuery.refetch()}
              disabled={listQuery.isFetching}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {listQuery.isFetching ? "Refreshing…" : "Refresh"}
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="rounded-lg bg-[#3525cd] px-4 py-1.5 text-sm font-semibold text-white hover:bg-[#2a1db0]"
            >
              + New incident
            </button>
          </div>
        </div>
        <div className="mt-4">
          <SnapshotSummary />
        </div>
      </header>

      <div className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="flex flex-wrap items-end gap-3 border-b border-[#e4e1f2] px-5 py-4">
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Status
            <select
              value={activeOnly ? "__active__" : statusFilter}
              onChange={(e) => {
                if (e.target.value === "__active__") {
                  setActiveOnly(true);
                  setStatusFilter("");
                } else {
                  setActiveOnly(false);
                  setStatusFilter(e.target.value as IncidentStatus | "");
                }
                setPage(1);
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
              <option value="__active__">Active only</option>
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Severity
            <select
              value={severityFilter}
              onChange={(e) => {
                setSeverityFilter(e.target.value as IncidentSeverity | "");
                setPage(1);
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {SEVERITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {listQuery.isLoading ? (
          <LoadingState
            compact
            title="Loading incidents…"
            className="px-5 py-8"
          />
        ) : listQuery.isError ? (
          <div className="p-5">
            <ErrorState
              compact
              error={listQuery.error}
              description={getApiErrorMessage(listQuery.error)}
              onRetry={() => void listQuery.refetch()}
            />
          </div>
        ) : items.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-[#6d6985]">
            No incidents match the current filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#e4e1f2] bg-[#faf9ff] text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                <tr>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Severity</th>
                  <th className="px-3 py-2">Title</th>
                  <th className="px-3 py-2">Affected</th>
                  <th className="px-3 py-2">Started</th>
                  <th className="px-3 py-2 text-center" title="Public banner">
                    Banner
                  </th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((incident) => (
                  <IncidentRow
                    key={incident.id}
                    incident={incident}
                    onOpen={() => setOpenIncidentId(incident.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > 25 ? (
          <div className="flex items-center justify-between border-t border-[#e4e1f2] px-5 py-3">
            <p className="text-xs text-[#6d6985]">
              {total.toLocaleString()} total — page {page} of {totalPages}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                ← Prev
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next →
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
