import { useTranslations } from "next-intl";

import {
  buildConnectorRootChips,
  getConnectorProviderLabel,
} from "@/components/chat/chat-connectors";
import type { ChatScopeController } from "@/components/chat/hooks/useChatScope";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";

export function ScopeConnectorSection({
  scope,
}: {
  scope: ChatScopeController;
}) {
  const tc = useTranslations("chat.page");
  const {
    connectorConnectionsQuery,
    connectorConnections,
    selectedConnectorConnectionIds,
    selectedProviderSourceIds,
    toggleConnectorConnection,
    toggleProviderSource,
  } = scope;

  return (
    <div className="mb-4 rounded-xl border border-[#e8e5f3] bg-[#faf9ff] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
            {tc("connectorSourcesTitle")}
          </p>
          <p className="text-xs text-[#6a6780]">
            {tc("connectorSourcesSubtitle")}
          </p>
        </div>
        <span className="rounded-full bg-[#ece8ff] px-2 py-1 text-[10px] font-semibold text-[#3525cd]">
          {tc("numSelected", {
            n:
              selectedConnectorConnectionIds.length +
              selectedProviderSourceIds.length,
          })}
        </span>
      </div>
      {connectorConnectionsQuery.isLoading ? (
        <LoadingState compact title={tc("loadingConnectors")} />
      ) : connectorConnectionsQuery.isError ? (
        <ErrorState
          compact
          error={connectorConnectionsQuery.error}
          description={getApiErrorMessage(connectorConnectionsQuery.error)}
          onRetry={() => {
            void connectorConnectionsQuery.refetch();
          }}
        />
      ) : connectorConnections.length === 0 ? (
        <p className="text-xs text-[#777587]">{tc("noConnectors")}</p>
      ) : (
        <div className="space-y-2">
          {connectorConnections.map((connection) => {
            const rootChips = buildConnectorRootChips(connection);
            const connectionSelected = selectedConnectorConnectionIds.includes(
              connection.id,
            );
            return (
              <div
                key={connection.id}
                className="rounded-lg border border-[#e2dff1] bg-white p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => toggleConnectorConnection(connection.id)}
                    className={`flex min-w-0 flex-1 items-start gap-2 text-left transition-colors ${
                      connectionSelected ? "text-[#3525cd]" : "text-[#2f2a46]"
                    }`}
                  >
                    <span
                      className={`material-symbols-outlined mt-0.5 text-[18px] ${connectionSelected ? "text-[#3525cd]" : "text-[#6a6780]"}`}
                      aria-hidden="true"
                    >
                      hub
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold">
                        {connection.display_name}
                      </span>
                      <span className="block text-[11px] text-[#6a6780]">
                        {getConnectorProviderLabel(connection.provider_key)}
                        {connection.external_account_id
                          ? ` · ${connection.external_account_id}`
                          : ""}
                      </span>
                    </span>
                  </button>
                  <span
                    className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
                      connectionSelected
                        ? "bg-[#ece8ff] text-[#3525cd]"
                        : "bg-[#f1f0f5] text-[#6a6780]"
                    }`}
                  >
                    {connectionSelected
                      ? tc("connectionSelected")
                      : tc("connectionSelect")}
                  </span>
                </div>
                {rootChips.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {rootChips.map((root) => {
                      const selected = selectedProviderSourceIds.includes(
                        root.label,
                      );
                      return (
                        <button
                          key={root.id}
                          type="button"
                          onClick={() => {
                            if (!connectionSelected) {
                              toggleConnectorConnection(connection.id);
                            }
                            toggleProviderSource(root.label);
                          }}
                          className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                            selected
                              ? "border-[#3525cd] bg-[#ece8ff] text-[#3525cd]"
                              : "border-[#d2cee6] bg-[#faf9ff] text-[#5f5a74] hover:border-[#b9b2dd] hover:bg-white"
                          }`}
                        >
                          {root.label}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-[#777587]">
                    {tc("useConnectionForAll")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
