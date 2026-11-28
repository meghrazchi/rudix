"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useTranslations } from "next-intl";
import { getApiErrorMessage } from "@/lib/api/errors";
import { inviteTeamMember, type TeamInviteRole } from "@/lib/api/team";
import {
  inviteSchema,
  type InviteValues,
} from "@/components/admin/team/teamShared";

export function InviteDialog({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const t = useTranslations("adminTeam");
  const localizedInviteSchema = useMemo(
    () =>
      inviteSchema.extend({
        email: z
          .string()
          .trim()
          .min(1, t("validation.emailRequired"))
          .email(t("validation.emailInvalid")),
      }),
    [t],
  );
  const form = useForm<InviteValues>({
    resolver: zodResolver(localizedInviteSchema),
    defaultValues: { email: "", name: "", role: "member" },
  });
  const [apiError, setApiError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: inviteTeamMember,
    onSuccess: () => {
      onSuccess();
    },
    onError: (err) => {
      setApiError(getApiErrorMessage(err));
    },
  });

  async function handleSubmit(values: InviteValues) {
    setApiError(null);
    const trimmedName = values.name?.trim();
    await mutation.mutateAsync({
      email: values.email.trim().toLowerCase(),
      role: values.role as TeamInviteRole,
      ...(trimmedName ? { name: trimmedName } : {}),
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label={t("inviteDialog.title")}
      >
        <div className="flex items-center justify-between border-b border-[#ebe8f7] px-6 py-4">
          <h2 className="text-base font-bold text-[#2a2640]">
            {t("inviteDialog.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("closeDialog")}
            className="rounded p-1 text-[#777587] hover:bg-[#f0edf9] hover:text-[#2f2a46]"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>
        <form
          onSubmit={form.handleSubmit(handleSubmit)}
          noValidate
          className="space-y-4 p-6"
        >
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("inviteDialog.emailLabel")}
            </label>
            <input
              type="email"
              placeholder={t("inviteDialog.emailPlaceholder")}
              {...form.register("email")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
            {form.formState.errors.email && (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.email.message}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("inviteDialog.nameLabel")}{" "}
              <span className="font-normal text-[#999] normal-case">
                {t("optional")}
              </span>
            </label>
            <input
              type="text"
              placeholder={t("inviteDialog.namePlaceholder")}
              autoComplete="name"
              {...form.register("name")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("inviteDialog.roleLabel")}
            </label>
            <select
              {...form.register("role")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd]"
            >
              <option value="admin">{t("roles.admin")}</option>
              <option value="member">{t("roles.member")}</option>
              <option value="viewer">{t("roles.viewer")}</option>
              <option value="reviewer">{t("roles.reviewer")}</option>
              <option value="developer">{t("roles.developer")}</option>
              <option value="security_admin">{t("roles.securityAdmin")}</option>
              <option value="billing_admin">{t("roles.billingAdmin")}</option>
            </select>
          </div>
          {apiError && (
            <p
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800"
            >
              {apiError}
            </p>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#4b4662] hover:bg-[#f8f6ff]"
            >
              {t("actions.cancel")}
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {mutation.isPending
                ? t("actions.sending")
                : t("actions.sendInvite")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
