"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { usePermissions } from "@/lib/use-permissions";
import {
  searchOrgUsers,
  simulateAccess,
  type ExtendedStatus,
  type OrgMemberResult,
  type ReasonChainEntry,
  type SimulateAccessResponse,
  type SimulateTraceStep,
  type TroubleshootingLink,
} from "@/lib/api/access-debugger";

// ── Constants ──────────────────────────────────────────────────────────────────

const RESOURCE_TYPES = [
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

const ACTIONS = [
  "list",
  "view",
  "search",
  "chat",
  "cite",
  "create",
  "manage",
  "sync",
  "export",
  "evaluate",
  "delete",
];

const STATUS_CONFIG: Record<
  ExtendedStatus,
  { labelKey: string; color: string; bg: string; icon: string }
> = {
  allowed: {
    labelKey: "allowed",
    color: "text-emerald-700",
    bg: "bg-emerald-50 border-emerald-200",
    icon: "✓",
  },
  inherited: {
    labelKey: "inherited",
    color: "text-emerald-700",
    bg: "bg-emerald-50 border-emerald-200",
    icon: "↑",
  },
  denied: {
    labelKey: "denied",
    color: "text-red-700",
    bg: "bg-red-50 border-red-200",
    icon: "✗",
  },
  restricted: {
    labelKey: "restricted",
    color: "text-amber-700",
    bg: "bg-amber-50 border-amber-200",
    icon: "⊘",
  },
  unavailable: {
    labelKey: "unavailable",
    color: "text-slate-600",
    bg: "bg-slate-50 border-slate-200",
    icon: "—",
  },
  stale_acl: {
    labelKey: "staleAcl",
    color: "text-amber-700",
    bg: "bg-amber-50 border-amber-200",
    icon: "⚠",
  },
  unknown: {
    labelKey: "unknown",
    color: "text-slate-600",
    bg: "bg-slate-50 border-slate-200",
    icon: "?",
  },
};

const LAYER_KEYS: Record<string, string> = {
  organization_membership: "organizationMembership",
  role: "rolePermissions",
  custom_permission: "customPermission",
  collection_policy: "collectionPolicy",
  document_acl: "resourceAcl",
  connector_acl: "connectorAcl",
  source_ownership: "sourceOwnership",
  graph_acl: "graphAcl",
  share_policy: "sharePolicy",
  system_policy: "systemPolicy",
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function TraceStepRow({ step }: { step: SimulateTraceStep }) {
  const t = useTranslations("adminAccessDebugger");
  const dot =
    step.outcome === "allow"
      ? "bg-emerald-400"
      : step.outcome === "deny"
        ? "bg-red-400"
        : "bg-slate-300";
  const label =
    step.outcome === "allow"
      ? "text-emerald-600"
      : step.outcome === "deny"
        ? "text-red-600"
        : "text-slate-400";
  return (
    <div className="flex items-start gap-3 py-1.5">
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
      <div className="flex-1 text-xs">
        <span className="font-mono text-[#2a2640]">{step.rule}</span>
        <span className={`ml-2 font-bold uppercase ${label}`}>
          {t(`outcomes.${step.outcome}`)}
        </span>
        {step.detail && (
          <span className="ml-2 text-[#68647b]">({step.detail})</span>
        )}
      </div>
    </div>
  );
}

function ReasonChainRow({ entry }: { entry: ReasonChainEntry }) {
  const t = useTranslations("adminAccessDebugger");
  const isTerminal = entry.outcome !== "pass";
  return (
    <div
      className={`flex items-start gap-3 rounded-lg px-3 py-2 ${
        isTerminal
          ? entry.outcome === "allow"
            ? "border border-emerald-100 bg-emerald-50"
            : "border border-red-100 bg-red-50"
          : "border border-[#ede9fb] bg-white"
      }`}
    >
      <span
        className={`mt-0.5 text-xs font-bold ${
          entry.outcome === "allow"
            ? "text-emerald-600"
            : entry.outcome === "deny"
              ? "text-red-600"
              : "text-slate-400"
        }`}
      >
        {entry.outcome === "allow" ? "✓" : entry.outcome === "deny" ? "✗" : "·"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-[#2a2640]">
          {LAYER_KEYS[entry.layer]
            ? t(`layers.${LAYER_KEYS[entry.layer]}`)
            : entry.layer}
        </p>
        {entry.detail && (
          <p className="text-[11px] text-[#68647b]">{entry.detail}</p>
        )}
      </div>
      <span
        className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${
          entry.outcome === "allow"
            ? "bg-emerald-100 text-emerald-700"
            : entry.outcome === "deny"
              ? "bg-red-100 text-red-700"
              : "bg-slate-100 text-slate-500"
        }`}
      >
        {t(`outcomes.${entry.outcome}`)}
      </span>
    </div>
  );
}

function PermissionsPanel({ permissions }: { permissions: string[] }) {
  const t = useTranslations("adminAccessDebugger");
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? permissions : permissions.slice(0, 8);
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {visible.map((p) => (
          <span
            key={p}
            className="rounded-full bg-[#f0eeff] px-2 py-0.5 font-mono text-[10px] text-[#3525cd]"
          >
            {p}
          </span>
        ))}
      </div>
      {permissions.length > 8 && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-2 text-xs text-[#3525cd] hover:underline"
        >
          {expanded
            ? t("showLess")
            : t("more", { count: permissions.length - 8 })}
        </button>
      )}
    </div>
  );
}

function TroubleshootingLinks({ links }: { links: TroubleshootingLink[] }) {
  const t = useTranslations("adminAccessDebugger");
  return (
    <div className="flex flex-wrap gap-3">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className="inline-flex items-center gap-1 rounded-lg border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs font-medium text-[#3525cd] transition hover:border-[#3525cd] hover:bg-[#f0eeff]"
        >
          {link.href === "/admin/audit-logs"
            ? t("links.auditLogs")
            : link.href === "/admin/permissions"
              ? t("links.accessManagement")
              : link.label}
          <svg
            className="h-3 w-3"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
            />
          </svg>
        </Link>
      ))}
    </div>
  );
}

// ── User search autocomplete ───────────────────────────────────────────────────

function UserSelector({
  value,
  onSelect,
}: {
  value: OrgMemberResult | null;
  onSelect: (user: OrgMemberResult | null) => void;
}) {
  const t = useTranslations("adminAccessDebugger");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const { data, isFetching } = useQuery({
    queryKey: ["access-debugger", "users", query],
    queryFn: () => searchOrgUsers({ q: query, limit: 10 }),
    enabled: open && query.length >= 0,
    placeholderData: (prev) => prev,
  });

  const handleSelect = useCallback(
    (user: OrgMemberResult) => {
      onSelect(user);
      setQuery(user.display_name ?? user.email);
      setOpen(false);
    },
    [onSelect],
  );

  const handleClear = useCallback(() => {
    onSelect(null);
    setQuery("");
    inputRef.current?.focus();
  }, [onSelect]);

  return (
    <div className="relative">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={value ? (value.display_name ?? value.email) : query}
          onChange={(e) => {
            if (value) {
              onSelect(null);
            }
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={t("userSearch.placeholder")}
          role="combobox"
          className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 pr-8 text-sm focus:border-[#3525cd] focus:outline-none"
          aria-label={t("userSearch.ariaLabel")}
          aria-autocomplete="list"
          aria-controls="user-search-listbox"
          aria-expanded={open}
        />
        {value && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute end-2 top-1/2 -translate-y-1/2 text-[#a09dbf] hover:text-[#2a2640]"
            aria-label={t("userSearch.clear")}
          >
            ✕
          </button>
        )}
      </div>

      {open && (
        <div
          id="user-search-listbox"
          className="absolute z-20 mt-1 w-full rounded-xl border border-[#d7d4e8] bg-white shadow-lg"
          role="listbox"
        >
          {isFetching && (
            <p className="px-4 py-3 text-xs text-[#68647b]">
              {t("userSearch.searching")}
            </p>
          )}
          {!isFetching && data?.items.length === 0 && (
            <p className="px-4 py-3 text-xs text-[#68647b]">
              {t("userSearch.empty")}
            </p>
          )}
          {!isFetching &&
            data?.items.map((user) => (
              <button
                key={user.user_id}
                type="button"
                role="option"
                aria-selected={false}
                onMouseDown={() => handleSelect(user)}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left first:rounded-t-xl last:rounded-b-xl hover:bg-[#f0eeff]"
              >
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#3525cd] text-[10px] font-bold text-white uppercase">
                  {(user.display_name ?? user.email).slice(0, 2)}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-[#2a2640]">
                    {user.display_name ?? user.email}
                  </p>
                  <p className="truncate text-[10px] text-[#68647b]">
                    {user.email}
                  </p>
                </div>
                <span className="ms-auto shrink-0 rounded-full bg-[#ede9fb] px-2 py-0.5 text-[10px] font-semibold text-[#5d58a8]">
                  {user.role}
                </span>
              </button>
            ))}
        </div>
      )}

      {value && (
        <p className="mt-1 text-[10px] text-[#a09dbf]">ID: {value.user_id}</p>
      )}
    </div>
  );
}

// ── Result panel ───────────────────────────────────────────────────────────────

function ResultPanel({ result }: { result: SimulateAccessResponse }) {
  const t = useTranslations("adminAccessDebugger");
  const cfg = STATUS_CONFIG[result.extended_status] ?? STATUS_CONFIG.unknown;
  const [showTrace, setShowTrace] = useState(false);
  const [showPerms, setShowPerms] = useState(false);

  return (
    <div className="space-y-5" data-testid="result-panel">
      {/* Decision banner */}
      <div className={`rounded-xl border p-5 ${cfg.bg}`}>
        <div className="flex flex-wrap items-start gap-4">
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-full text-lg font-bold ${cfg.color} border bg-white`}
          >
            {cfg.icon}
          </div>
          <div className="flex-1">
            <p className={`text-lg font-bold ${cfg.color}`}>
              {t(`statuses.${cfg.labelKey}`)}
            </p>
            <p className="mt-0.5 text-xs text-[#68647b]">
              {t("result.rule")}:{" "}
              <span className="font-mono text-[#2a2640]">
                {result.matched_rule}
              </span>
              {result.deny_reason && (
                <span className="ml-3">
                  {t("result.reason")}:{" "}
                  <span className="font-mono text-red-700">
                    {result.deny_reason}
                  </span>
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Subject + resource summary */}
        <div className="mt-4 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
          <div className="rounded-lg bg-white/70 px-3 py-2">
            <p className="text-[10px] font-bold text-[#5d58a8] uppercase">
              {t("result.subject")}
            </p>
            <p className="mt-1 font-semibold text-[#2a2640]">
              {result.subject_display_name ?? result.subject_email}
            </p>
            <p className="text-[#68647b]">{result.subject_email}</p>
            <span className="mt-1 inline-block rounded-full bg-[#ede9fb] px-2 py-0.5 text-[10px] font-semibold text-[#5d58a8]">
              {result.subject_role}
            </span>
          </div>
          <div className="rounded-lg bg-white/70 px-3 py-2">
            <p className="text-[10px] font-bold text-[#5d58a8] uppercase">
              {t("result.resource")}
            </p>
            <p className="mt-1 font-semibold text-[#2a2640]">
              {result.resource_type}
            </p>
            {result.resource_id && (
              <p className="font-mono text-[11px] break-all text-[#68647b]">
                {result.resource_id}
              </p>
            )}
            <span className="mt-1 inline-block rounded-full bg-[#ede9fb] px-2 py-0.5 text-[10px] font-semibold text-[#5d58a8]">
              {result.action}
            </span>
          </div>
        </div>
      </div>

      {/* Reason chain */}
      {result.reason_chain.length > 0 && (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs font-bold text-[#5d58a8] uppercase">
            {t("result.reasonChain")}
          </p>
          <div className="space-y-2">
            {result.reason_chain.map((entry, i) => (
              <ReasonChainRow key={i} entry={entry} />
            ))}
          </div>
        </div>
      )}

      {/* Remediation */}
      {result.remediation.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="mb-2 text-xs font-bold text-amber-700 uppercase">
            {t("result.howToGrant")}
          </p>
          <ul className="space-y-1.5">
            {result.remediation.map((r, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-sm text-amber-900"
              >
                <span className="mt-0.5 shrink-0 text-amber-600">→</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Troubleshooting links */}
      {result.troubleshooting_links.length > 0 && (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs font-bold text-[#5d58a8] uppercase">
            {t("result.troubleshoot")}
          </p>
          <TroubleshootingLinks links={result.troubleshooting_links} />
        </div>
      )}

      {/* Effective permissions (collapsible) */}
      {result.effective_permissions.length > 0 && (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <button
            type="button"
            onClick={() => setShowPerms((v) => !v)}
            className="flex w-full items-center justify-between text-xs font-bold text-[#5d58a8] uppercase"
          >
            <span>
              {t("result.effectivePermissions", {
                count: result.effective_permissions.length,
              })}
            </span>
            <span>{showPerms ? "▲" : "▼"}</span>
          </button>
          {showPerms && (
            <div className="mt-3">
              <PermissionsPanel permissions={result.effective_permissions} />
            </div>
          )}
        </div>
      )}

      {/* Policy trace (collapsible) */}
      {result.trace.length > 0 && (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <button
            type="button"
            onClick={() => setShowTrace((v) => !v)}
            className="flex w-full items-center justify-between text-xs font-bold text-[#5d58a8] uppercase"
          >
            <span>
              {t("result.policyTrace", { count: result.trace.length })}
            </span>
            <span>{showTrace ? "▲" : "▼"}</span>
          </button>
          {showTrace && (
            <div className="mt-3 divide-y divide-[#ede9fb] rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-4 py-3">
              {result.trace.map((step, i) => (
                <TraceStepRow key={i} step={step} />
              ))}
            </div>
          )}
        </div>
      )}

      <p className="text-[10px] text-[#a09dbf]">
        {t("result.requestId")}: {result.request_id}
      </p>
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────────

function EmptyState() {
  const t = useTranslations("adminAccessDebugger");
  return (
    <div
      className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#d7d4e8] bg-[#f9f8ff] px-8 py-16 text-center"
      data-testid="empty-state"
    >
      <svg
        className="mb-4 h-10 w-10 text-[#a09dbf]"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
        />
      </svg>
      <p className="text-sm font-semibold text-[#2a2640]">{t("empty.title")}</p>
      <p className="mt-1 text-xs text-[#68647b]">{t("empty.description")}</p>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function AdminAccessDebuggerPage() {
  const t = useTranslations("adminAccessDebugger");
  const { hasPermission } = usePermissions();

  const [selectedUser, setSelectedUser] = useState<OrgMemberResult | null>(
    null,
  );
  const [resourceType, setResourceType] = useState("document");
  const [action, setAction] = useState("view");
  const [resourceId, setResourceId] = useState("");
  const [result, setResult] = useState<SimulateAccessResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const simulateMutation = useMutation({
    mutationFn: () =>
      simulateAccess({
        subject_user_id: selectedUser!.user_id,
        resource_type: resourceType,
        action,
        resource_id: resourceId.trim() || null,
      }),
    onSuccess: (data) => {
      setResult(data);
      setFormError(null);
    },
    onError: (err) => {
      setFormError(getApiErrorMessage(err));
      setResult(null);
    },
  });

  if (!hasPermission("security_center:view")) {
    return (
      <ForbiddenState
        title={t("title")}
        description={t("errors.permissionRequired")}
        backHref="/admin"
      />
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedUser) {
      setFormError(t("errors.selectUser"));
      return;
    }
    simulateMutation.mutate();
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8">
      {/* Header */}
      <div>
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("eyebrow")}
        </p>
        <h1 className="text-2xl font-extrabold text-[#2a2640]">{t("title")}</h1>
        <p className="mt-1 text-sm text-[#68647b]">{t("description")}</p>
      </div>

      {/* Security note */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong>{t("securityNoteLabel")}</strong> {t("securityNote")}
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-5">
        {/* Left: form */}
        <div className="lg:col-span-2">
          <form
            onSubmit={handleSubmit}
            className="space-y-5 rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
          >
            <h2 className="text-sm font-bold text-[#2a2640]">
              {t("form.title")}
            </h2>

            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#2a2640]">
                {t("form.subjectUser")} <span className="text-red-500">*</span>
              </label>
              <UserSelector value={selectedUser} onSelect={setSelectedUser} />
            </div>

            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#2a2640]">
                {t("form.resourceType")}
              </label>
              <select
                value={resourceType}
                onChange={(e) => setResourceType(e.target.value)}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                {RESOURCE_TYPES.map((rt) => (
                  <option key={rt} value={rt}>
                    {rt}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#2a2640]">
                {t("form.action")}
              </label>
              <select
                value={action}
                onChange={(e) => setAction(e.target.value)}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#2a2640]">
                {t("form.resourceId")}{" "}
                <span className="font-normal text-[#68647b]">
                  {t("form.resourceIdOptional")}
                </span>
              </label>
              <input
                type="text"
                value={resourceId}
                onChange={(e) => setResourceId(e.target.value)}
                placeholder={t("form.resourceIdPlaceholder")}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 font-mono text-sm focus:border-[#3525cd] focus:outline-none"
              />
              <p className="text-[10px] text-[#a09dbf]">
                {t("form.resourceIdHelp")}
              </p>
            </div>

            {formError && (
              <p
                className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
                role="alert"
              >
                {formError}
              </p>
            )}

            <button
              type="submit"
              disabled={simulateMutation.isPending || !selectedUser}
              className="w-full rounded-lg bg-[#3525cd] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
            >
              {simulateMutation.isPending
                ? t("form.simulating")
                : t("form.simulate")}
            </button>
          </form>
        </div>

        {/* Right: result */}
        <div className="lg:col-span-3">
          {simulateMutation.isPending && (
            <div
              className="flex h-48 items-center justify-center rounded-xl border border-[#d7d4e8] bg-white"
              role="status"
              aria-live="polite"
              aria-label={t("form.simulatingAccess")}
              data-testid="loading-state"
            >
              <p className="text-sm text-[#68647b]">{t("form.simulating")}</p>
            </div>
          )}
          {!simulateMutation.isPending && result && (
            <ResultPanel result={result} />
          )}
          {!simulateMutation.isPending && !result && <EmptyState />}
        </div>
      </div>
    </div>
  );
}
