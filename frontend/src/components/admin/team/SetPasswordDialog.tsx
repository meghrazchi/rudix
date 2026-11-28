"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useTranslations } from "next-intl";
import { getApiErrorMessage } from "@/lib/api/errors";
import { setMemberPassword, type TeamMember } from "@/lib/api/team";

export type SetPasswordValues = { password: string; confirm: string };

export function SetPasswordDialog({
  member,
  onClose,
  onSuccess,
}: {
  member: TeamMember;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const t = useTranslations("adminTeam");
  const localizedPasswordSchema = useMemo(
    () =>
      z
        .object({
          password: z.string().min(8, t("validation.passwordLength")).max(128),
          confirm: z.string(),
        })
        .refine((value) => value.password === value.confirm, {
          message: t("validation.passwordMismatch"),
          path: ["confirm"],
        }),
    [t],
  );
  const form = useForm<SetPasswordValues>({
    resolver: zodResolver(localizedPasswordSchema),
    defaultValues: { password: "", confirm: "" },
  });
  const [apiError, setApiError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const mutation = useMutation({
    mutationFn: ({
      memberId,
      password,
    }: {
      memberId: string;
      password: string;
    }) => setMemberPassword(memberId, password),
    onSuccess: () => onSuccess(),
    onError: (err) => setApiError(getApiErrorMessage(err)),
  });

  async function handleSubmit(values: SetPasswordValues) {
    setApiError(null);
    await mutation.mutateAsync({
      memberId: member.member_id,
      password: values.password,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label={t("password.dialogLabel")}
      >
        <div className="flex items-center justify-between border-b border-[#ebe8f7] px-6 py-4">
          <div>
            <h2 className="text-base font-bold text-[#2a2640]">
              {t("password.title")}
            </h2>
            <p className="mt-0.5 text-xs text-[#777587]">
              {member.name || member.email}
            </p>
          </div>
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
          className="space-y-4 p-6"
        >
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("password.newPassword")}
            </label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                placeholder={t("password.minCharacters")}
                autoComplete="new-password"
                {...form.register("password")}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 pr-10 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute top-1/2 right-2.5 -translate-y-1/2 text-[#999] hover:text-[#555]"
                aria-label={
                  showPassword ? t("password.hide") : t("password.show")
                }
              >
                {showPassword ? (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            {form.formState.errors.password && (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.password.message}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("password.confirm")}
            </label>
            <input
              type={showPassword ? "text" : "password"}
              placeholder={t("password.repeat")}
              autoComplete="new-password"
              {...form.register("confirm")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
            {form.formState.errors.confirm && (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.confirm.message}
              </p>
            )}
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
              {mutation.isPending ? t("actions.saving") : t("password.title")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
