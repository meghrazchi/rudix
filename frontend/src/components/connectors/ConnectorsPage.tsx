"use client";

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { listProviders } from "@/lib/api/connector-providers";
import {
  disconnectConnector,
  listConnectorConnections,
} from "@/lib/api/connectors";
import type { ConnectorConnectionsListResponse } from "@/lib/api/connectors";
import { queryKeys } from "@/lib/api/query";

// ── Types ─────────────────────────────────────────────────────────────────────

type ConnectionRow = {
  id: string;
  providerKey: string;
  name: string;
  projectLabel: string;
  status: "active" | "error" | "paused";
  lastSyncLabel: string;
  lastSyncStatus: string;
  itemsIndexed: number;
  errorMessage: string | null;
};

type CatalogEntry = {
  key: string;
  name: string;
  description: string;
  brandColor: string;
  initial: string;
  connected: boolean;
  available: boolean;
};

const CATALOG: CatalogEntry[] = [
  {
    key: "jira",
    name: "Jira",
    description: "Sync issues, epics, and documentation from Jira Cloud.",
    brandColor: "#0052CC",
    initial: "J",
    connected: false,
    available: true,
  },
  {
    key: "confluence",
    name: "Confluence",
    description: "Import wiki pages, team spaces, and technical documents.",
    brandColor: "#0052CC",
    initial: "C",
    connected: false,
    available: true,
  },
  {
    key: "google_drive",
    name: "Google Drive",
    description: "Index Docs, Sheets, and shared corporate drive folders.",
    brandColor: "#4285F4",
    initial: "G",
    connected: false,
    available: true,
  },
  {
    key: "sharepoint",
    name: "SharePoint",
    description: "Connect Microsoft 365 sites and enterprise file libraries.",
    brandColor: "#0078D4",
    initial: "S",
    connected: false,
    available: false,
  },
  {
    key: "notion",
    name: "Notion",
    description: "Access workspace databases, project docs, and notes.",
    brandColor: "#000000",
    initial: "N",
    connected: false,
    available: false,
  },
  {
    key: "slack",
    name: "Slack",
    description: "Retrieve conversational history from public/private channels.",
    brandColor: "#4A154B",
    initial: "S",
    connected: false,
    available: false,
  },
  {
    key: "github",
    name: "GitHub",
    description: "Index source code, PR discussions, and repository wikis.",
    brandColor: "#24292E",
    initial: "G",
    connected: false,
    available: false,
  },
  {
    key: "gitlab",
    name: "GitLab",
    description: "Synchronize self-hosted or cloud-based repo data.",
    brandColor: "#FC6D26",
    initial: "GL",
    connected: false,
    available: false,
  },
];

function connectionToRow(connection: {
  id: string;
  provider_key: string;
  display_name: string;
  external_account_id: string | null;
  status: string;
  last_sync_at: string | null;
  source_count: number;
  error_message: string | null;
}): ConnectionRow {
  return {
    id: connection.id,
    providerKey: connection.provider_key,
    name: connection.display_name,
    projectLabel: connection.external_account_id
      ? `Account: ${connection.external_account_id}`
      : `Provider: ${connection.provider_key}`,
    status:
      connection.status === "active"
        ? "active"
        : connection.status === "paused"
          ? "paused"
          : "error",
    lastSyncLabel: connection.last_sync_at
      ? new Date(connection.last_sync_at).toLocaleString()
      : "Never",
    lastSyncStatus:
      connection.status === "active"
        ? "Success"
        : connection.status === "paused"
          ? "Paused"
          : connection.status === "error"
            ? "Needs attention"
            : "Unknown",
    itemsIndexed: connection.source_count,
    errorMessage: connection.error_message,
  };
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatCard({
  icon,
  iconColor,
  iconBg,
  topBorderColor,
  label,
  value,
  badge,
  badgeColor,
}: {
  icon: string;
  iconColor: string;
  iconBg: string;
  topBorderColor: string;
  label: string;
  value: string;
  badge: string;
  badgeColor: string;
}) {
  return (
    <div
      className={`bg-white border border-[#c7c4d8] border-t-4 ${topBorderColor} p-6 rounded-xl shadow-sm hover:shadow-md transition-shadow`}
    >
      <div className="flex items-center justify-between mb-4">
        <span
          className={`material-symbols-outlined ${iconColor} ${iconBg} p-2 rounded-lg text-[22px]`}
        >
          {icon}
        </span>
        <span className={`text-[11px] font-semibold uppercase tracking-wide ${badgeColor}`}>
          {badge}
        </span>
      </div>
      <div className="text-xs font-semibold uppercase tracking-wide text-[#464555] mb-1">
        {label}
      </div>
      <div className="text-4xl font-semibold text-[#1b1b24]">{value}</div>
    </div>
  );
}

function StatusBadge({ status, errorMessage }: { status: ConnectionRow["status"]; errorMessage: string | null }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1.5 bg-emerald-100 text-emerald-800 text-[11px] font-bold px-2 py-1 rounded">
        <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
        ACTIVE
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        className="inline-flex items-center gap-1.5 bg-red-100 text-red-800 text-[11px] font-bold px-2 py-1 rounded cursor-help"
        title={errorMessage ?? undefined}
      >
        <span className="w-1.5 h-1.5 bg-red-500 rounded-full" />
        ERROR
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 bg-[#e4e1ee] text-[#464555] text-[11px] font-bold px-2 py-1 rounded">
      PAUSED
    </span>
  );
}

function ProviderIcon({
  brandColor,
  initial,
  size = "md",
}: {
  brandColor: string;
  initial: string;
  size?: "sm" | "md";
}) {
  const dim = size === "sm" ? "w-10 h-10 text-sm" : "w-12 h-12 text-base";
  return (
    <div
      className={`${dim} rounded-lg flex items-center justify-center font-bold text-white shadow-sm shrink-0`}
      style={{ backgroundColor: brandColor }}
    >
      {initial}
    </div>
  );
}

function CatalogCard({ entry, onConnect }: { entry: CatalogEntry; onConnect: (key: string) => void }) {
  if (entry.connected) {
    return (
      <div className="relative bg-white border-2 border-[#3525cd] p-6 rounded-xl shadow-sm hover:shadow-lg transition-all overflow-hidden">
        <div className="absolute top-0 right-0 bg-[#3525cd] text-white text-[10px] font-bold px-2 py-1 rounded-bl-lg tracking-wide">
          CONNECTED
        </div>
        <ProviderIcon brandColor={entry.brandColor} initial={entry.initial} />
        <h4 className="text-lg font-semibold text-[#1b1b24] mt-4 mb-1">{entry.name}</h4>
        <p className="text-xs text-[#464555] mb-4 leading-relaxed">{entry.description}</p>
        <button
          onClick={() => onConnect(entry.key)}
          className="block w-full text-center border border-[#3525cd] text-[#3525cd] text-xs font-bold py-2 rounded-lg hover:bg-[#3525cd]/10 transition-colors uppercase tracking-wide"
        >
          Add another
        </button>
      </div>
    );
  }

  if (entry.available) {
    return (
      <div className="bg-white border border-[#c7c4d8] p-6 rounded-xl shadow-sm hover:shadow-md hover:border-[#3525cd]/40 transition-all">
        <ProviderIcon brandColor={entry.brandColor} initial={entry.initial} />
        <h4 className="text-lg font-semibold text-[#1b1b24] mt-4 mb-1">{entry.name}</h4>
        <p className="text-xs text-[#464555] mb-4 leading-relaxed">{entry.description}</p>
        <button
          onClick={() => onConnect(entry.key)}
          className="w-full bg-[#3525cd] text-white text-xs font-bold py-2 rounded-lg hover:opacity-90 transition-opacity uppercase tracking-wide"
        >
          Connect
        </button>
      </div>
    );
  }

  // Coming soon
  return (
    <div className="bg-[#f0ecf9]/50 border border-[#c7c4d8] p-6 rounded-xl grayscale hover:grayscale-0 hover:shadow-md transition-all opacity-80">
      <div
        className="w-12 h-12 rounded-lg flex items-center justify-center font-bold text-white/60 text-base shadow-sm shrink-0 opacity-40"
        style={{ backgroundColor: entry.brandColor }}
      >
        {entry.initial}
      </div>
      <div className="flex items-center justify-between mt-4 mb-1">
        <h4 className="text-lg font-semibold text-[#464555]">{entry.name}</h4>
        <span className="text-[10px] bg-[#e4e1ee] text-[#464555] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide">
          Soon
        </span>
      </div>
      <p className="text-xs text-[#464555] mb-4 leading-relaxed">{entry.description}</p>
      <button
        disabled
        className="w-full bg-[#e4e1ee] text-[#464555] text-xs font-bold py-2 rounded-lg cursor-not-allowed uppercase tracking-wide"
      >
        Notify me
      </button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ConnectorsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const catalogRef = useRef<HTMLElement>(null);

  const providersQuery = useQuery({
    queryKey: queryKeys.connectorProviders,
    queryFn: listProviders,
  });
  const connectionsQuery = useQuery({
    queryKey: queryKeys.connectorConnections,
    queryFn: listConnectorConnections,
  });

  const allConnections = connectionsQuery.data?.items ?? [];
  const connectedCount = allConnections.length;
  const runningCount = allConnections.filter((c) => c.status === "active").length;
  const failedCount = allConnections.filter((c) => c.status === "error").length;
  const reauthCount = allConnections.filter(
    (c) => c.status === "error" && c.error_message != null,
  ).length;
  const connectionRows = allConnections.map(connectionToRow);
  const connectedProviderKeys = new Set(
    allConnections.map((c) => c.provider_key),
  );
  const providerKeysFromAPI = new Set(
    (providersQuery.data?.items ?? []).map((provider) => provider.key),
  );

  const deleteConnectionMutation = useMutation({
    mutationFn: (connectionId: string) => disconnectConnector(connectionId),
    onMutate: async (connectionId) => {
      await queryClient.cancelQueries({
        queryKey: queryKeys.connectorConnections,
      });

      const previousConnections = queryClient.getQueryData<ConnectorConnectionsListResponse>(
        queryKeys.connectorConnections,
      );

      queryClient.setQueryData(
        queryKeys.connectorConnections,
        (
          current: ConnectorConnectionsListResponse | undefined,
        ): ConnectorConnectionsListResponse | undefined => {
          if (!current) {
            return current;
          }
          const nextItems = current.items.filter(
            (item) => item.id !== connectionId,
          );
          return {
            items: nextItems,
            total: nextItems.length,
          };
        },
      );

      return { previousConnections };
    },
    onError: (_error, _connectionId, context) => {
      if (context?.previousConnections) {
        queryClient.setQueryData(
          queryKeys.connectorConnections,
          context.previousConnections,
        );
      }
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnections,
      });
    },
  });

  function handleConnect(providerKey: string) {
    router.push(`/connectors/new/${encodeURIComponent(providerKey)}`);
  }

  function handleDeleteConnection(connectionId: string, connectionName: string) {
    const confirmed = window.confirm(
      `Delete connected source \"${connectionName}\"? This will disconnect it from Rudix.`,
    );
    if (!confirmed) {
      return;
    }
    deleteConnectionMutation.mutate(connectionId);
  }

  function scrollToCatalog() {
    catalogRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <div className="p-8 max-w-[1200px]">
      {/* Page title */}
      <section className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24] mb-1">
          Connectors
        </h1>
        <p className="text-base text-[#464555]">
          Connect external knowledge sources and keep Rudix in sync.
        </p>
      </section>

      {/* Health bento grid */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          icon="database"
          iconColor="text-[#3525cd]"
          iconBg="bg-[#3525cd]/10"
          topBorderColor="border-t-[#3525cd]"
          label="Connected sources"
          value={connectedCount.toString().padStart(2, "0")}
          badge={connectedCount > 0 ? `${connectedCount} total` : "None yet"}
          badgeColor="text-[#3525cd]"
        />
        <StatCard
          icon="sync"
          iconColor="text-[#7e3000]"
          iconBg="bg-[#ffdbcc]/60"
          topBorderColor="border-t-[#7e3000]"
          label="Syncs active"
          value={runningCount.toString().padStart(2, "0")}
          badge={runningCount > 0 ? "Active" : "None active"}
          badgeColor="text-[#7e3000]"
        />
        <StatCard
          icon="error_outline"
          iconColor="text-[#ba1a1a]"
          iconBg="bg-[#ffdad6]"
          topBorderColor="border-t-[#ba1a1a]"
          label="Failed syncs"
          value={failedCount.toString().padStart(2, "0")}
          badge={failedCount > 0 ? "Needs attention" : "All clear"}
          badgeColor={failedCount > 0 ? "text-[#ba1a1a]" : "text-emerald-700"}
        />
        <StatCard
          icon="key"
          iconColor="text-[#505f76]"
          iconBg="bg-[#d0e1fb]"
          topBorderColor="border-t-[#505f76]"
          label="Reauth required"
          value={reauthCount.toString().padStart(2, "0")}
          badge={reauthCount > 0 ? "Action required" : "All healthy"}
          badgeColor={reauthCount > 0 ? "text-[#505f76]" : "text-emerald-700"}
        />
      </section>

      {/* Connected sources table */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-2xl font-semibold text-[#1b1b24]">
            Connected sources
          </h2>
          <button
            type="button"
            onClick={scrollToCatalog}
            className="inline-flex items-center gap-1.5 bg-[#3525cd] text-white text-xs font-bold py-2 px-5 rounded-lg hover:opacity-90 transition-opacity uppercase tracking-wide"
          >
            <span className="material-symbols-outlined text-[18px]">add</span>
            Add new source
          </button>
        </div>

        <div className="bg-white border border-[#c7c4d8] rounded-xl overflow-hidden shadow-sm">
          <table className="w-full text-left border-collapse">
            <thead className="bg-[#eae6f4] border-b border-[#c7c4d8]">
              <tr>
                {["Source", "Status", "Last Sync", "Items Indexed", "Actions"].map(
                  (h) => (
                    <th
                      key={h}
                      className={`px-6 py-3 text-[11px] font-semibold uppercase tracking-wide text-[#464555] ${
                        h === "Actions" ? "text-right" : ""
                      }`}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e4e1ee]">
              {connectionRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <span className="material-symbols-outlined text-[40px] text-[#c7c4d8]">
                        cloud_off
                      </span>
                      <div className="text-sm text-[#464555]">
                        No sources connected yet.
                      </div>
                      <button
                        type="button"
                        onClick={scrollToCatalog}
                        className="text-xs font-semibold text-[#3525cd] hover:underline"
                      >
                        Browse the catalog below
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                connectionRows.map((conn) => {
                  const catalog = CATALOG.find((c) => c.key === conn.providerKey);
                  return (
                    <tr
                      key={conn.id}
                      className="hover:bg-[#f5f2ff] transition-colors group"
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          {catalog && (
                            <ProviderIcon
                              brandColor={catalog.brandColor}
                              initial={catalog.initial}
                              size="sm"
                            />
                          )}
                          <div>
                            <div className="font-semibold text-sm text-[#1b1b24]">
                              {conn.name}
                            </div>
                            <div className="text-xs text-[#464555]">
                              {conn.projectLabel}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <StatusBadge status={conn.status} errorMessage={conn.errorMessage} />
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-mono text-[13px] text-[#1b1b24]">
                          {conn.lastSyncLabel}
                        </div>
                        <div className="text-[11px] text-[#464555] uppercase tracking-wide">
                          {conn.lastSyncStatus}
                        </div>
                      </td>
                      <td className="px-6 py-4 font-mono text-[13px] text-[#1b1b24]">
                        {conn.itemsIndexed.toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-1 opacity-40 group-hover:opacity-100 transition-opacity">
                          <button
                            title="View details"
                            aria-label={`View details for ${conn.name}`}
                            className="p-2 hover:bg-[#e4e1ee] rounded-lg transition-colors text-[#464555]"
                            onClick={() => router.push(`/connectors/${conn.id}`)}
                          >
                            <span className="material-symbols-outlined text-[20px]">
                              visibility
                            </span>
                          </button>
                          <button
                            title="Sync now"
                            aria-label={`Sync now for ${conn.name}`}
                            className="p-2 hover:bg-[#e4e1ee] rounded-lg transition-colors text-[#464555]"
                            onClick={() => router.push(`/connectors/${conn.id}`)}
                          >
                            <span className="material-symbols-outlined text-[20px]">
                              sync
                            </span>
                          </button>
                          <button
                            title="Settings"
                            aria-label={`Settings for ${conn.name}`}
                            className="p-2 hover:bg-[#e4e1ee] rounded-lg transition-colors text-[#464555]"
                            onClick={() => router.push(`/connectors/${conn.id}`)}
                          >
                            <span className="material-symbols-outlined text-[20px]">
                              settings
                            </span>
                          </button>
                          <button
                            title="Delete"
                            aria-label={`Delete connected source ${conn.name}`}
                            disabled={deleteConnectionMutation.isPending}
                            onClick={() =>
                              handleDeleteConnection(conn.id, conn.name)
                            }
                            className="p-2 hover:bg-[#fce8e6] rounded-lg transition-colors text-[#b42318] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <span className="material-symbols-outlined text-[20px]">
                              delete
                            </span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Connector catalog */}
      <section ref={catalogRef}>
        <div className="mb-5">
          <h2 className="text-2xl font-semibold text-[#1b1b24] mb-1">
            Connector catalog
          </h2>
          <p className="text-sm text-[#464555]">
            Choose from our growing library of native integrations.
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {CATALOG.filter(
            (entry) => providerKeysFromAPI.has(entry.key) || entry.available,
          ).map((entry) => (
            <CatalogCard
              key={entry.key}
              entry={{
                ...entry,
                connected: connectedProviderKeys.has(entry.key),
              }}
              onConnect={handleConnect}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
