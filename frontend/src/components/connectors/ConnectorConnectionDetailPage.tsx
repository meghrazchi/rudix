"use client";

import Link from "next/link";
import { useMemo } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { ConnectorSyncPanel } from "@/components/connectors/ConnectorSyncPanel";
import { getApiErrorMessage, type ApiClientError } from "@/lib/api/errors";
import {
  disconnectConnector,
  getConnectorConnection,
  refreshConnectorCredential,
} from "@/lib/api/connectors";
import { queryKeys } from "@/lib/api/query";

type Props = {
  connectionId: string;
};

function ConnectionStatusBadge({ status }: { status: string }) {
  const label = status.replace(/_/g, " ");
  const className =
    status === "active"
      ? "bg-emerald-100 text-emerald-800"
      : status === "paused"
        ? "bg-amber-100 text-amber-800"
        : status === "revoked" || status === "disabled"
          ? "bg-slate-100 text-slate-700"
          : "bg-rose-100 text-rose-800";

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${className}`}
    >
      {label}
    </span>
  );
}

function formatList(values: unknown): string[] {
  if (Array.isArray(values)) {
    return values
      .map((value) => String(value))
      .filter((value) => value.trim().length > 0);
  }
  if (typeof values === "string" && values.trim().length > 0) {
    return [values];
  }
  return [];
}

function ScopeField({ label, value }: { label: string; value: string[] }) {
  if (value.length === 0) {
    return null;
  }
  return (
    <div className="rounded-xl border border-[#e8e5f3] bg-white p-3">
      <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
        {label}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {value.map((item) => (
          <span
            key={item}
            className="rounded-full bg-[#ece8ff] px-2.5 py-1 text-xs font-semibold text-[#3525cd]"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function PermissionSnapshotField({
  snapshot,
}: {
  snapshot: {
    id: string;
    provider_source_id: string;
    name: string;
    source_type: string;
    is_enabled: boolean;
    permissions: Record<string, unknown>;
  };
}) {
  return (
    <div className="rounded-xl border border-[#e8e5f3] bg-[#faf9fe] p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-[#2a2640]">
            {snapshot.name}
          </div>
          <div className="mt-1 text-xs text-[#6a6780]">
            {snapshot.source_type} · {snapshot.provider_source_id}
          </div>
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            snapshot.is_enabled
              ? "bg-emerald-100 text-emerald-800"
              : "bg-slate-100 text-slate-700"
          }`}
        >
          {snapshot.is_enabled ? "Active" : "Disabled"}
        </span>
      </div>
      <div className="mt-3 text-xs text-[#6a6780]">Permission snapshot</div>
      <pre className="mt-1 rounded-lg bg-white p-2 text-[11px] leading-5 break-words whitespace-pre-wrap text-[#4b4860]">
        {JSON.stringify(snapshot.permissions, null, 2)}
      </pre>
    </div>
  );
}

function scopeFields(providerKey: string, authConfig: Record<string, unknown>) {
  if (providerKey === "confluence") {
    return [
      { label: "Space keys", value: formatList(authConfig.space_keys) },
      {
        label: "CQL filter",
        value:
          typeof authConfig.cql_filter === "string" &&
          authConfig.cql_filter.trim().length > 0
            ? [authConfig.cql_filter]
            : [],
      },
      {
        label: "Include comments",
        value: authConfig.include_comments ? ["Enabled"] : [],
      },
    ];
  }
  if (providerKey === "google_drive") {
    return [
      { label: "Folder IDs", value: formatList(authConfig.folder_ids) },
      { label: "Shared Drive IDs", value: formatList(authConfig.drive_ids) },
      {
        label: "Shared drives",
        value: authConfig.include_shared_drives ? ["Included"] : [],
      },
    ];
  }
  if (providerKey === "microsoft-sharepoint-onedrive") {
    return [
      { label: "SharePoint site IDs", value: formatList(authConfig.site_ids) },
      { label: "Drive IDs", value: formatList(authConfig.drive_ids) },
      { label: "Folder IDs", value: formatList(authConfig.folder_ids) },
      {
        label: "Allowed file types",
        value: formatList(authConfig.allowed_file_types),
      },
      {
        label: "Include folder paths",
        value: formatList(authConfig.include_folder_paths),
      },
      {
        label: "Exclude folder paths",
        value: formatList(authConfig.exclude_folder_paths),
      },
      {
        label: "Sync frequency",
        value:
          typeof authConfig.sync_frequency_minutes === "number"
            ? [`${authConfig.sync_frequency_minutes} minutes`]
            : [],
      },
      {
        label: "Permission import",
        value:
          typeof authConfig.permission_import_behavior === "string"
            ? [authConfig.permission_import_behavior]
            : [],
      },
    ];
  }
  return Object.entries(authConfig).map(([label, value]) => ({
    label: label.replace(/_/g, " "),
    value: Array.isArray(value)
      ? value.map((item) => String(item))
      : typeof value === "string"
        ? [value]
        : [],
  }));
}

function ErrorPanel({ error }: { error: ApiClientError }) {
  const label =
    error.status === 403
      ? "Permission denied"
      : error.status === 429
        ? "Rate limited"
        : error.status === 404
          ? "Connection not found"
          : "Unable to load connection";
  return (
    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-900">
      <div className="font-semibold">{label}</div>
      <p className="mt-1">{getApiErrorMessage(error)}</p>
    </div>
  );
}

export function ConnectorConnectionDetailPage({ connectionId }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const connectionQuery = useQuery({
    queryKey: queryKeys.connectorConnection(connectionId),
    queryFn: () => getConnectorConnection(connectionId),
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshConnectorCredential(connectionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnection(connectionId),
      });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: () => disconnectConnector(connectionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnections,
      });
      router.push("/connectors");
    },
  });

  const connection = connectionQuery.data;
  const permissionSnapshots = connection?.source_permission_snapshots ?? [];
  const scope = useMemo(
    () =>
      connection
        ? scopeFields(connection.provider_key, connection.auth_config ?? {})
        : [],
    [connection],
  );

  if (connectionQuery.isLoading) {
    return (
      <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
        <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-6 text-sm text-[#68647b]">
          Loading connector details…
        </div>
      </section>
    );
  }

  if (connectionQuery.isError || !connection) {
    return (
      <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
        <ErrorPanel error={connectionQuery.error as ApiClientError} />
        <Link
          href="/connectors"
          className="inline-flex items-center rounded-xl border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#3525cd]"
        >
          Back to connectors
        </Link>
      </section>
    );
  }

  const safeDiagnostics = connection.diagnostics ?? {
    auth_type: null,
    credential_status: null,
    credential_version: null,
    credential_fingerprint: null,
    scopes: [],
    expires_at: null,
    error_message: null,
    connection_id: connection.id,
    provider_key: connection.provider_key,
    status: connection.status,
    metadata: {},
  };
  const connectionProblem =
    connection.status === "error" ||
    safeDiagnostics.credential_status === "error"
      ? "This connector needs attention before the next sync can succeed."
      : null;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Connector details
            </p>
            <h1 className="text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              {connection.display_name}
            </h1>
            <p className="mt-2 text-sm text-[#68647b]">
              {connection.provider.display_name}
              {connection.external_account_id
                ? ` · ${connection.external_account_id}`
                : ""}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
              className="rounded-xl border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
            >
              Reconnect
            </button>
            <button
              type="button"
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
              className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Disconnect
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <ConnectionStatusBadge status={connection.status} />
          {safeDiagnostics.credential_status && (
            <span className="rounded-full bg-[#ece8ff] px-2.5 py-0.5 text-xs font-semibold text-[#3525cd]">
              Credential {safeDiagnostics.credential_status}
            </span>
          )}
          {safeDiagnostics.expires_at && (
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
              Expires {safeDiagnostics.expires_at}
            </span>
          )}
        </div>

        {connectionProblem && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {connectionProblem}
          </div>
        )}
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            Status
          </div>
          <div className="mt-2">
            <ConnectionStatusBadge status={connection.status} />
          </div>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            Sync scopes
          </div>
          <div className="mt-2 text-3xl font-extrabold text-[#2a2640]">
            {scope.filter((item) => item.value.length > 0).length}
          </div>
          <div className="mt-1 text-sm text-[#68647b]">
            Saved source filters
          </div>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            Last sync
          </div>
          <div className="mt-2 text-lg font-bold text-[#2a2640]">
            {connection.last_sync_at ?? "Never"}
          </div>
          <div className="mt-1 text-sm text-[#68647b]">
            Connection lifecycle state
          </div>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            Auth
          </div>
          <div className="mt-2 text-lg font-bold text-[#2a2640]">
            {safeDiagnostics.auth_type ?? "n/a"}
          </div>
          <div className="mt-1 text-sm text-[#68647b]">
            {safeDiagnostics.scopes.length > 0
              ? `${safeDiagnostics.scopes.length} scopes granted`
              : "No credential snapshot yet"}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr,0.9fr]">
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="mb-4">
            <h2 className="text-lg font-bold text-[#2a2640]">
              Selected source scope
            </h2>
            <p className="text-sm text-[#68647b]">
              Provider-specific scope metadata that drives selected projects,
              spaces, or folders.
            </p>
          </div>
          <div className="space-y-3">
            {scope.filter((field) => field.value.length > 0).length === 0 && (
              <div className="rounded-xl border border-dashed border-[#d7d4e8] bg-[#faf9fe] p-4 text-sm text-[#68647b]">
                No explicit scope has been stored for this connection yet.
              </div>
            )}
            {scope.map((field) => (
              <ScopeField
                key={field.label}
                label={field.label}
                value={field.value}
              />
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="mb-4">
            <h2 className="text-lg font-bold text-[#2a2640]">
              Credential diagnostics
            </h2>
            <p className="text-sm text-[#68647b]">
              Safe metadata for health, token state, and trust checks.
            </p>
          </div>
          <div className="space-y-3 text-sm text-[#4b4860]">
            <div className="rounded-xl bg-[#faf9fe] p-3">
              <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
                Credential status
              </div>
              <div className="mt-1 font-semibold text-[#2a2640]">
                {safeDiagnostics.credential_status ?? "unknown"}
              </div>
            </div>
            <div className="rounded-xl bg-[#faf9fe] p-3">
              <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
                Granted scopes
              </div>
              <div className="mt-1 flex flex-wrap gap-2">
                {safeDiagnostics.scopes.length === 0 && (
                  <span className="text-[#68647b]">No scopes cached.</span>
                )}
                {safeDiagnostics.scopes.map((scopeValue) => (
                  <span
                    key={scopeValue}
                    className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-[#3525cd]"
                  >
                    {scopeValue}
                  </span>
                ))}
              </div>
            </div>
            <div className="rounded-xl bg-[#faf9fe] p-3">
              <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
                Trust state
              </div>
              <div className="mt-1 font-semibold text-[#2a2640]">
                {safeDiagnostics.credential_status === "revoked" ||
                connection.status === "revoked"
                  ? "Revoked"
                  : safeDiagnostics.credential_status === "error" ||
                      connection.status === "error"
                    ? "Needs attention"
                    : "Healthy"}
              </div>
            </div>
          </div>
        </section>
      </div>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="mb-4">
          <h2 className="text-lg font-bold text-[#2a2640]">
            Access review hooks
          </h2>
          <p className="text-sm text-[#68647b]">
            Permission snapshots that can drive review workflows and
            source-level governance.
          </p>
        </div>
        {permissionSnapshots.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] bg-[#faf9fe] p-4 text-sm text-[#68647b]">
            No source permission snapshots have been recorded yet.
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {permissionSnapshots.map((snapshot) => (
              <PermissionSnapshotField key={snapshot.id} snapshot={snapshot} />
            ))}
          </div>
        )}
      </section>

      <ConnectorSyncPanel connectionId={connection.id} />
    </section>
  );
}
