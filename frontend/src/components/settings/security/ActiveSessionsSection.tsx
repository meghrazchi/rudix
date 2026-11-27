"use client";

import { Users } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getSecurityCapabilities,
  getSessions,
  revokeSession,
  revokeAllOtherSessions,
} from "@/lib/api/security";
import { queryKeys } from "@/lib/api/query";
import {
  formatTimestamp,
  SectionHeader,
  DeploymentControlledBadge,
  SaveFeedback,
  type SaveState,
} from "@/components/settings/security/securityShared";

export function ActiveSessionsSection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getSecurityCapabilities>;
}) {
  const t = useTranslations("settings.security");

  const sessionsQuery = useQuery({
    queryKey: queryKeys.security.sessions,
    queryFn: getSessions,
    enabled: capabilities.sessionsEnabled,
    retry: false,
  });

  const [revokeState, setRevokeState] = useState<SaveState>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const revokeSessionMutation = useMutation({
    mutationFn: (sessionId: string) => revokeSession(sessionId),
    onSuccess: () => {
      void sessionsQuery.refetch();
      setRevokeState({ tone: "success", message: t("sessions.revoked") });
      setRevokingId(null);
    },
    onError: (error) => {
      setRevokeState({ tone: "error", message: getApiErrorMessage(error) });
      setRevokingId(null);
    },
  });

  const revokeAllMutation = useMutation({
    mutationFn: revokeAllOtherSessions,
    onSuccess: () => {
      void sessionsQuery.refetch();
      setRevokeState({
        tone: "success",
        message: t("sessions.allRevoked"),
      });
    },
    onError: (error) => {
      setRevokeState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  function handleRevokeSession(sessionId: string, device: string): void {
    const confirmed = window.confirm(
      `Revoke session for "${device}"? That device will be signed out immediately.`,
    );
    if (!confirmed) return;
    setRevokeState(null);
    setRevokingId(sessionId);
    revokeSessionMutation.mutate(sessionId);
  }

  function handleRevokeAll(): void {
    const confirmed = window.confirm(
      "Revoke all other active sessions? Every device except the current one will be signed out immediately.",
    );
    if (!confirmed) return;
    setRevokeState(null);
    revokeAllMutation.mutate();
  }

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Active sessions section"
    >
      <SectionHeader
        icon={Users}
        title={t("sessions.title")}
        badge={
          !capabilities.sessionsEnabled && (
            <DeploymentControlledBadge label={t("deploymentControlled")} />
          )
        }
      />

      {!capabilities.sessionsEnabled ? (
        <p className="text-sm text-[#777587]">{t("sessions.unavailable")}</p>
      ) : sessionsQuery.isLoading ? (
        <LoadingState compact title={t("sessions.loading")} />
      ) : sessionsQuery.isError ? (
        isApiClientError(sessionsQuery.error) &&
        sessionsQuery.error.status === 429 ? (
          <RateLimitState
            compact
            onRetry={() => {
              void sessionsQuery.refetch();
            }}
          />
        ) : isApiClientError(sessionsQuery.error) &&
          sessionsQuery.error.status === 403 ? (
          <ForbiddenState
            compact
            title={t("sessions.restrictedTitle")}
            description={t("sessions.restrictedDesc")}
            backHref="/dashboard"
            backLabel={t("backToDashboard")}
          />
        ) : (
          <ErrorState
            compact
            error={sessionsQuery.error}
            description={getApiErrorMessage(sessionsQuery.error)}
            onRetry={() => {
              void sessionsQuery.refetch();
            }}
          />
        )
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-[#e4e1ee]">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#f5f2ff] text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                <tr>
                  <th className="px-4 py-3">{t("sessions.device")}</th>
                  <th className="px-4 py-3">{t("sessions.location")}</th>
                  <th className="px-4 py-3">{t("sessions.lastActive")}</th>
                  <th className="px-4 py-3 text-right">
                    {t("sessions.action")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e4e1ee]">
                {(sessionsQuery.data ?? []).length === 0 && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-4 text-center text-sm text-[#777587]"
                    >
                      {t("sessions.noSessions")}
                    </td>
                  </tr>
                )}
                {(sessionsQuery.data ?? []).map((s) => (
                  <tr
                    key={s.id}
                    className="transition-colors hover:bg-[#f5f2ff]/40"
                  >
                    <td className="px-4 py-3">
                      <span className="font-semibold text-[#1b1b24]">
                        {s.device}
                      </span>
                      {s.is_current && (
                        <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                          {t("sessions.current")}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[#464555]">
                      {s.location ?? t("sessions.unknown")}
                    </td>
                    <td className="px-4 py-3 text-[#464555]">
                      {formatTimestamp(s.last_active_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {s.is_current ? (
                        <span className="text-xs text-[#777587]">
                          {t("sessions.thisDevice")}
                        </span>
                      ) : capabilities.revokeSessionEnabled ? (
                        <button
                          type="button"
                          disabled={
                            revokingId === s.id ||
                            revokeSessionMutation.isPending
                          }
                          onClick={() => handleRevokeSession(s.id, s.device)}
                          className="text-sm font-semibold text-[#777587] transition-colors hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {revokingId === s.id
                            ? t("sessions.revoking")
                            : t("sessions.revoke")}
                        </button>
                      ) : (
                        <span className="text-xs text-[#777587]">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {capabilities.revokeAllSessionsEnabled &&
            (sessionsQuery.data?.length ?? 0) > 1 && (
              <div className="mt-4 flex items-center justify-between gap-4">
                <SaveFeedback state={revokeState} />
                <button
                  type="button"
                  disabled={
                    revokeAllMutation.isPending ||
                    revokeSessionMutation.isPending
                  }
                  onClick={handleRevokeAll}
                  className="ml-auto rounded-xl border border-rose-200 px-4 py-2 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {revokeAllMutation.isPending
                    ? t("sessions.revokingAll")
                    : t("sessions.revokeAll")}
                </button>
              </div>
            )}

          {revokeState && !capabilities.revokeAllSessionsEnabled && (
            <div className="mt-3">
              <SaveFeedback state={revokeState} />
            </div>
          )}
        </>
      )}
    </section>
  );
}
