"use client";

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import { OnboardingCtaBanner } from "@/components/onboarding/OnboardingCtaBanner";
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

const CATALOG: Omit<CatalogEntry, "description">[] = [
  {
    key: "confluence",
    name: "Confluence",
    brandColor: "#0052CC",
    initial: "C",
    connected: false,
    available: true,
  },
  {
    key: "google_drive",
    name: "Google Drive",
    brandColor: "#4285F4",
    initial: "G",
    connected: false,
    available: true,
  },
  {
    key: "microsoft-sharepoint-onedrive",
    name: "SharePoint / OneDrive",
    brandColor: "#0078D4",
    initial: "M",
    connected: false,
    available: true,
  },
  {
    key: "notion",
    name: "Notion",
    brandColor: "#000000",
    initial: "N",
    connected: false,
    available: true,
  },
  {
    key: "slack",
    name: "Slack",
    brandColor: "#4A154B",
    initial: "S",
    connected: false,
    available: false,
  },
  {
    key: "github",
    name: "GitHub",
    brandColor: "#24292E",
    initial: "G",
    connected: false,
    available: false,
  },
  {
    key: "gitlab",
    name: "GitLab",
    brandColor: "#FC6D26",
    initial: "GL",
    connected: false,
    available: false,
  },
];

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
      className={`border border-t-4 border-[#c7c4d8] bg-white ${topBorderColor} rounded-xl p-6 shadow-sm transition-shadow hover:shadow-md`}
    >
      <div className="mb-4 flex items-center justify-between">
        <span
          className={`material-symbols-outlined ${iconColor} ${iconBg} rounded-lg p-2 text-[22px]`}
        >
          {icon}
        </span>
        <span
          className={`text-[11px] font-semibold tracking-wide uppercase ${badgeColor}`}
        >
          {badge}
        </span>
      </div>
      <div className="mb-1 text-xs font-semibold tracking-wide text-[#464555] uppercase">
        {label}
      </div>
      <div className="text-4xl font-semibold text-[#1b1b24]">{value}</div>
    </div>
  );
}

function StatusBadge({
  status,
  errorMessage,
}: {
  status: ConnectionRow["status"];
  errorMessage: string | null;
}) {
  const t = useTranslations("connectors.page.status");

  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded bg-emerald-100 px-2 py-1 text-[11px] font-bold text-emerald-800">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
        {t("active")}
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        className="inline-flex cursor-help items-center gap-1.5 rounded bg-red-100 px-2 py-1 text-[11px] font-bold text-red-800"
        title={errorMessage ?? undefined}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
        {t("error")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded bg-[#e4e1ee] px-2 py-1 text-[11px] font-bold text-[#464555]">
      {t("paused")}
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
      className={`${dim} flex shrink-0 items-center justify-center rounded-lg font-bold text-white shadow-sm`}
      style={{ backgroundColor: brandColor }}
    >
      {initial}
    </div>
  );
}

function CatalogCard({
  entry,
  onConnect,
}: {
  entry: CatalogEntry;
  onConnect: (key: string) => void;
}) {
  const t = useTranslations("connectors.page.catalog");

  if (entry.connected) {
    return (
      <div className="relative overflow-hidden rounded-xl border-2 border-[#3525cd] bg-white p-6 shadow-sm transition-all hover:shadow-lg">
        <div className="absolute top-0 right-0 rounded-bl-lg bg-[#3525cd] px-2 py-1 text-[10px] font-bold tracking-wide text-white">
          {t("connected")}
        </div>
        <ProviderIcon brandColor={entry.brandColor} initial={entry.initial} />
        <h4 className="mt-4 mb-1 text-lg font-semibold text-[#1b1b24]">
          {entry.name}
        </h4>
        <p className="mb-4 text-xs leading-relaxed text-[#464555]">
          {entry.description}
        </p>
        <button
          onClick={() => onConnect(entry.key)}
          className="block w-full rounded-lg border border-[#3525cd] py-2 text-center text-xs font-bold tracking-wide text-[#3525cd] uppercase transition-colors hover:bg-[#3525cd]/10"
        >
          {t("addAnother")}
        </button>
      </div>
    );
  }

  if (entry.available) {
    return (
      <div className="rounded-xl border border-[#c7c4d8] bg-white p-6 shadow-sm transition-all hover:border-[#3525cd]/40 hover:shadow-md">
        <ProviderIcon brandColor={entry.brandColor} initial={entry.initial} />
        <h4 className="mt-4 mb-1 text-lg font-semibold text-[#1b1b24]">
          {entry.name}
        </h4>
        <p className="mb-4 text-xs leading-relaxed text-[#464555]">
          {entry.description}
        </p>
        <button
          onClick={() => onConnect(entry.key)}
          className="w-full rounded-lg bg-[#3525cd] py-2 text-xs font-bold tracking-wide text-white uppercase transition-opacity hover:opacity-90"
        >
          {t("connect")}
        </button>
      </div>
    );
  }

  // Coming soon
  return (
    <div className="rounded-xl border border-[#c7c4d8] bg-[#f0ecf9]/50 p-6 opacity-80 grayscale transition-all hover:shadow-md hover:grayscale-0">
      <div
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg text-base font-bold text-white/60 opacity-40 shadow-sm"
        style={{ backgroundColor: entry.brandColor }}
      >
        {entry.initial}
      </div>
      <div className="mt-4 mb-1 flex items-center justify-between">
        <h4 className="text-lg font-semibold text-[#464555]">{entry.name}</h4>
        <span className="rounded bg-[#e4e1ee] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-[#464555] uppercase">
          {t("soon")}
        </span>
      </div>
      <p className="mb-4 text-xs leading-relaxed text-[#464555]">
        {entry.description}
      </p>
      <button
        disabled
        className="w-full cursor-not-allowed rounded-lg bg-[#e4e1ee] py-2 text-xs font-bold tracking-wide text-[#464555] uppercase"
      >
        {t("notifyMe")}
      </button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ConnectorsPage() {
  const t = useTranslations("connectors.page");
  const tNav = useTranslations("navigation");
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
  const runningCount = allConnections.filter(
    (c) => c.status === "active",
  ).length;
  const failedCount = allConnections.filter((c) => c.status === "error").length;
  const reauthCount = allConnections.filter(
    (c) => c.status === "error" && c.error_message != null,
  ).length;

  const connectionRows: ConnectionRow[] = allConnections.map((c) => ({
    id: c.id,
    providerKey: c.provider_key,
    name: c.display_name,
    projectLabel: c.external_account_id
      ? t("table.accountLabel", { id: c.external_account_id })
      : t("table.providerLabel", { key: c.provider_key }),
    status:
      c.status === "active"
        ? "active"
        : c.status === "paused"
          ? "paused"
          : "error",
    lastSyncLabel: c.last_sync_at
      ? new Date(c.last_sync_at).toLocaleString()
      : t("table.lastSyncNever"),
    lastSyncStatus:
      c.status === "active"
        ? t("table.syncStatusSuccess")
        : c.status === "paused"
          ? t("table.syncStatusPaused")
          : c.status === "error"
            ? t("table.syncStatusNeedsAttention")
            : t("table.syncStatusUnknown"),
    itemsIndexed: c.indexed_document_count,
    errorMessage: c.error_message,
  }));

  const connectedProviderKeys = new Set(
    allConnections.map((c) => c.provider_key),
  );
  const providerKeysFromAPI = new Set(
    (providersQuery.data?.items ?? []).map((provider) => provider.key),
  );

  const catalogDescriptions: Record<string, string> = {
    confluence: t("catalog.confluenceDesc"),
    google_drive: t("catalog.googleDriveDesc"),
    "microsoft-sharepoint-onedrive": t("catalog.sharepointDesc"),
    notion: t("catalog.notionDesc"),
    slack: t("catalog.slackDesc"),
    github: t("catalog.githubDesc"),
    gitlab: t("catalog.gitlabDesc"),
  };

  const disconnectConnectionMutation = useMutation({
    mutationFn: (connectionId: string) => disconnectConnector(connectionId),
    onMutate: async (connectionId) => {
      await queryClient.cancelQueries({
        queryKey: queryKeys.connectorConnections,
      });

      const previousConnections =
        queryClient.getQueryData<ConnectorConnectionsListResponse>(
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

  function handleDisconnectConnection(
    connectionId: string,
    connectionName: string,
  ) {
    const confirmed = window.confirm(
      t("table.deleteConfirm", { name: connectionName }),
    );
    if (!confirmed) {
      return;
    }
    disconnectConnectionMutation.mutate(connectionId);
  }

  function scrollToCatalog() {
    catalogRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  const TABLE_HEADERS = [
    t("table.headerSource"),
    t("table.headerStatus"),
    t("table.headerLastSync"),
    t("table.headerItemsIndexed"),
    t("table.headerActions"),
  ];

  return (
    <div className="max-w-[1200px] p-8">
      {/* Page title */}
      <section className="mb-8">
        <div className="flex items-center gap-2">
          <h1 className="mb-1 text-3xl font-semibold tracking-tight text-[#1b1b24]">
            {tNav("connectors")}
          </h1>
          <ContextualHelpLink topic="manage-connectors" />
        </div>
        <p className="text-base text-[#464555]">{t("pageDescription")}</p>
      </section>

      {/* Health bento grid */}
      <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon="database"
          iconColor="text-[#3525cd]"
          iconBg="bg-[#3525cd]/10"
          topBorderColor="border-t-[#3525cd]"
          label={t("stats.connectedSources")}
          value={connectedCount.toString().padStart(2, "0")}
          badge={
            connectedCount > 0
              ? t("stats.total", { count: connectedCount })
              : t("stats.noneYet")
          }
          badgeColor="text-[#3525cd]"
        />
        <StatCard
          icon="sync"
          iconColor="text-[#7e3000]"
          iconBg="bg-[#ffdbcc]/60"
          topBorderColor="border-t-[#7e3000]"
          label={t("stats.syncsActive")}
          value={runningCount.toString().padStart(2, "0")}
          badge={runningCount > 0 ? t("stats.active") : t("stats.noneActive")}
          badgeColor="text-[#7e3000]"
        />
        <StatCard
          icon="error_outline"
          iconColor="text-[#ba1a1a]"
          iconBg="bg-[#ffdad6]"
          topBorderColor="border-t-[#ba1a1a]"
          label={t("stats.failedSyncs")}
          value={failedCount.toString().padStart(2, "0")}
          badge={
            failedCount > 0 ? t("stats.needsAttention") : t("stats.allClear")
          }
          badgeColor={failedCount > 0 ? "text-[#ba1a1a]" : "text-emerald-700"}
        />
        <StatCard
          icon="key"
          iconColor="text-[#505f76]"
          iconBg="bg-[#d0e1fb]"
          topBorderColor="border-t-[#505f76]"
          label={t("stats.reauthRequired")}
          value={reauthCount.toString().padStart(2, "0")}
          badge={
            reauthCount > 0 ? t("stats.actionRequired") : t("stats.allHealthy")
          }
          badgeColor={reauthCount > 0 ? "text-[#505f76]" : "text-emerald-700"}
        />
      </section>

      {/* Connected sources table */}
      <section className="mb-8">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-2xl font-semibold text-[#1b1b24]">
            {t("table.sectionTitle")}
          </h2>
        </div>

        <div className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
          <table className="w-full border-collapse text-left">
            <thead className="border-b border-[#c7c4d8] bg-[#eae6f4]">
              <tr>
                {TABLE_HEADERS.map((h) => (
                  <th
                    key={h}
                    className={`px-6 py-3 text-[11px] font-semibold tracking-wide text-[#464555] uppercase ${
                      h === t("table.headerActions") ? "text-right" : ""
                    }`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e4e1ee]">
              {connectionRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center">
                    <div className="flex flex-col items-center gap-4">
                      <span className="material-symbols-outlined text-[40px] text-[#c7c4d8]">
                        cloud_off
                      </span>
                      <div className="text-sm text-[#464555]">
                        {t("table.noSourcesYet")}
                      </div>
                      <button
                        type="button"
                        onClick={scrollToCatalog}
                        className="text-xs font-semibold text-[#3525cd] hover:underline"
                      >
                        {t("table.browseCatalog")}
                      </button>
                      <div className="w-full max-w-sm text-left">
                        <OnboardingCtaBanner
                          title="Connectors are optional"
                          description="You can also upload documents directly. Connectors sync from Jira, Confluence, Google Drive, and more automatically."
                          actionLabel="Upload documents instead"
                          actionHref="/documents"
                        />
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                connectionRows.map((conn) => {
                  const catalog = CATALOG.find(
                    (c) => c.key === conn.providerKey,
                  );
                  return (
                    <tr
                      key={conn.id}
                      className="group transition-colors hover:bg-[#f5f2ff]"
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
                            <div className="text-sm font-semibold text-[#1b1b24]">
                              {conn.name}
                            </div>
                            <div className="text-xs text-[#464555]">
                              {conn.projectLabel}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <StatusBadge
                          status={conn.status}
                          errorMessage={conn.errorMessage}
                        />
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-mono text-[13px] text-[#1b1b24]">
                          {conn.lastSyncLabel}
                        </div>
                        <div className="text-[11px] tracking-wide text-[#464555] uppercase">
                          {conn.lastSyncStatus}
                        </div>
                      </td>
                      <td className="px-6 py-4 font-mono text-[13px] text-[#1b1b24]">
                        {conn.itemsIndexed.toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-1 opacity-40 transition-opacity group-hover:opacity-100">
                          <button
                            title={t("table.titleViewDetails")}
                            aria-label={t("table.ariaViewDetails", {
                              name: conn.name,
                            })}
                            className="cursor-pointer rounded-lg p-2 text-[#464555] transition-colors hover:bg-[#e4e1ee]"
                            onClick={() =>
                              router.push(`/connectors/${conn.id}`)
                            }
                          >
                            <span className="material-symbols-outlined text-[20px]">
                              open_in_new
                            </span>
                          </button>
                          <button
                            title={t("table.titleViewDetails")}
                            aria-label={t("table.ariaDelete", {
                              name: conn.name,
                            })}
                            disabled={disconnectConnectionMutation.isPending}
                            onClick={() =>
                              handleDisconnectConnection(conn.id, conn.name)
                            }
                            className="cursor-pointer rounded-lg p-2 text-[#b42318] transition-colors hover:bg-[#fce8e6] disabled:cursor-not-allowed disabled:opacity-50"
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
          <h2 className="mb-1 text-2xl font-semibold text-[#1b1b24]">
            {t("catalog.sectionTitle")}
          </h2>
          <p className="text-sm text-[#464555]">
            {t("catalog.sectionDescription")}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          {CATALOG.filter(
            (entry) => providerKeysFromAPI.has(entry.key) || entry.available,
          ).map((entry) => (
            <CatalogCard
              key={entry.key}
              entry={{
                ...entry,
                description: catalogDescriptions[entry.key] ?? "",
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
