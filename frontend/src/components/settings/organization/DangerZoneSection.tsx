"use client";

import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  SaveFeedback,
  UnavailableRow,
  type SaveState,
} from "@/components/settings/organization/orgSettingsShared";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  archiveOrganization,
  deleteOrganization,
  exportOrganizationData,
  transferOwnership,
  type getOrganizationCapabilities,
} from "@/lib/api/organization";

export function DangerZoneSection({
  capabilities,
  session,
}: {
  capabilities: ReturnType<typeof getOrganizationCapabilities>;
  session: { organizationName?: string | null } | null;
}) {
  const t = useTranslations("settings.organization");

  const [dangerState, setDangerState] = useState<SaveState>(null);
  const [transferTarget, setTransferTarget] = useState("");

  const transferMutation = useMutation({
    mutationFn: (toUserId: string) => transferOwnership(toUserId),
    onSuccess: () => {
      setTransferTarget("");
      setDangerState({
        tone: "success",
        message: t("danger.transferInitiated"),
      });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: archiveOrganization,
    onSuccess: () => {
      setDangerState({
        tone: "success",
        message: t("danger.archiveSuccess"),
      });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportOrganizationData,
    onSuccess: (result) => {
      const msg = result.download_url
        ? `Export ready. Download URL: ${result.download_url}`
        : t("danger.exportSubmitted");
      setDangerState({ tone: "success", message: msg });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteOrganization,
    onSuccess: () => {
      setDangerState({
        tone: "success",
        message: t("danger.deletionInitiated"),
      });
    },
    onError: (error) => {
      setDangerState({ tone: "error", message: getApiErrorMessage(error) });
    },
  });

  const isDangerBusy =
    transferMutation.isPending ||
    archiveMutation.isPending ||
    exportMutation.isPending ||
    deleteMutation.isPending;

  return (
    <section
      className="rounded-2xl border border-rose-200 bg-white p-6"
      aria-label="Danger zone section"
    >
      <div className="mb-2 flex items-center gap-3">
        <AlertTriangle size={20} className="text-rose-600" aria-hidden="true" />
        <h2 className="text-lg font-semibold text-rose-700">
          {t("danger.title")}
        </h2>
      </div>
      <p className="mb-6 text-sm text-[#464555]">{t("danger.desc")}</p>

      <div className="space-y-4">
        {/* Transfer ownership */}
        {capabilities.transferOwnershipEnabled ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50/30 p-4">
            <p className="mb-2 text-sm font-semibold text-rose-700">
              {t("danger.transferTitle")}
            </p>
            <p className="mb-3 text-xs text-[#464555]">
              {t("danger.transferDesc")}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                type="text"
                value={transferTarget}
                onChange={(e) => setTransferTarget(e.target.value)}
                placeholder={t("danger.transferTarget")}
                disabled={isDangerBusy}
                aria-label={t("danger.transferTarget")}
                className="flex-1 rounded-xl border border-rose-200 bg-white px-3 py-2 text-sm outline-none focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 disabled:opacity-60"
              />
              <button
                type="button"
                disabled={!transferTarget.trim() || isDangerBusy}
                onClick={() => {
                  const target = transferTarget.trim();
                  if (!target) return;
                  const confirmed = window.confirm(
                    `Transfer ownership to user "${target}"? You will be downgraded to admin.`,
                  );
                  if (!confirmed) return;
                  setDangerState(null);
                  transferMutation.mutate(target);
                }}
                className="shrink-0 rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {transferMutation.isPending
                  ? t("danger.transferring")
                  : t("danger.transferBtn")}
              </button>
            </div>
          </div>
        ) : (
          <UnavailableRow
            label={t("danger.transferTitle")}
            description={t("danger.transferUnavailableDesc")}
            notAvailableMsg={t("notAvailableMsg")}
            unavailableLabel={t("unavailable")}
          />
        )}

        {/* Archive workspace */}
        {capabilities.archiveEnabled ? (
          <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50/30 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-rose-700">
                {t("danger.archiveTitle")}
              </p>
              <p className="text-xs text-[#464555]">
                {t("danger.archiveDesc")}
              </p>
            </div>
            <button
              type="button"
              disabled={isDangerBusy}
              onClick={() => {
                const confirmed = window.confirm(
                  "Archive this workspace? It will become read-only for all members.",
                );
                if (!confirmed) return;
                setDangerState(null);
                archiveMutation.mutate();
              }}
              className="shrink-0 rounded-xl border border-rose-300 px-3 py-1.5 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {archiveMutation.isPending
                ? t("danger.archiving")
                : t("danger.archiveBtn")}
            </button>
          </div>
        ) : (
          <UnavailableRow
            label={t("danger.archiveTitle")}
            description={t("danger.archiveUnavailableDesc")}
            notAvailableMsg={t("notAvailableMsg")}
            unavailableLabel={t("unavailable")}
          />
        )}

        {/* Export workspace data */}
        {capabilities.exportEnabled ? (
          <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50/30 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-rose-700">
                {t("danger.exportTitle")}
              </p>
              <p className="text-xs text-[#464555]">{t("danger.exportDesc")}</p>
            </div>
            <button
              type="button"
              disabled={isDangerBusy}
              onClick={() => {
                const confirmed = window.confirm(
                  "Request an export of all workspace data?",
                );
                if (!confirmed) return;
                setDangerState(null);
                exportMutation.mutate();
              }}
              className="shrink-0 rounded-xl border border-rose-300 px-3 py-1.5 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {exportMutation.isPending
                ? t("danger.requesting")
                : t("danger.exportBtn")}
            </button>
          </div>
        ) : (
          <UnavailableRow
            label={t("danger.exportTitle")}
            description={t("danger.exportUnavailableDesc")}
            notAvailableMsg={t("notAvailableMsg")}
            unavailableLabel={t("unavailable")}
          />
        )}

        {/* Delete organization */}
        {capabilities.deleteEnabled ? (
          <div className="flex items-start justify-between gap-4 rounded-xl border border-rose-300 bg-rose-50 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-rose-700">
                {t("danger.deleteTitle")}
              </p>
              <p className="text-xs text-[#464555]">{t("danger.deleteDesc")}</p>
            </div>
            <button
              type="button"
              disabled={isDangerBusy}
              onClick={() => {
                const orgName =
                  session?.organizationName ?? "this organization";
                const confirmed = window.confirm(
                  `Permanently delete "${orgName}"? All documents, chunks, vectors, chats, evaluations, and audit logs will be permanently removed. This cannot be undone.`,
                );
                if (!confirmed) return;
                setDangerState(null);
                deleteMutation.mutate();
              }}
              className="shrink-0 rounded-xl bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {deleteMutation.isPending
                ? t("danger.deleting")
                : t("danger.deleteBtn")}
            </button>
          </div>
        ) : (
          <UnavailableRow
            label={t("danger.deleteTitle")}
            description={t("danger.deleteUnavailableDesc")}
            notAvailableMsg={t("notAvailableMsg")}
            unavailableLabel={t("unavailable")}
          />
        )}
      </div>

      {dangerState ? (
        <div className="mt-4">
          <SaveFeedback state={dangerState} />
        </div>
      ) : null}
    </section>
  );
}
