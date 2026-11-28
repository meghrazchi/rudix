"use client";

import { useTranslations } from "next-intl";
import { type ConfirmAction } from "@/components/admin/team/teamShared";

export function ConfirmDialog({
  action,
  onConfirm,
  onCancel,
  isPending,
}: {
  action: ConfirmAction;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const t = useTranslations("adminTeam");
  const isDestructive = action.kind !== "revoke";
  const title =
    action.kind === "remove"
      ? t("confirmRemove.title", {
          name: action.member.name || action.member.email,
        })
      : action.kind === "deactivate"
        ? t("confirmDeactivate.title", {
            name: action.member.name || action.member.email,
          })
        : t("confirmRevoke.title", { email: action.invitation.email });

  const description =
    action.kind === "remove"
      ? t("confirmRemove.description")
      : action.kind === "deactivate"
        ? t("confirmDeactivate.description")
        : t("confirmRevoke.description");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-sm rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-xl"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2 className="mb-2 text-base font-bold text-[#2a2640]">{title}</h2>
        <p className="mb-6 text-sm text-[#6b6895]">{description}</p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:opacity-60"
          >
            {t("actions.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60 ${
              isDestructive
                ? "bg-rose-600 hover:bg-rose-700"
                : "bg-[#3525cd] hover:bg-[#2b1fa8]"
            }`}
          >
            {isPending
              ? t("actions.working")
              : action.kind === "remove"
                ? t("actions.remove")
                : action.kind === "deactivate"
                  ? t("actions.deactivate")
                  : t("actions.revoke")}
          </button>
        </div>
      </div>
    </div>
  );
}
