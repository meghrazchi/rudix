"use client";

import { useEffect, useRef, useState } from "react";

import { useTranslations } from "next-intl";

import type {
  CollectionAccessPolicy,
  DynamicRuleSet,
} from "@/lib/api/collections";
import { DynamicRuleBuilder } from "@/components/collections/DynamicRuleBuilder";

import { accessPolicyDescription } from "@/components/collections/collection-format";

// ── Collection form dialog ───────────────────────────────────────────────────

export type CollectionFormState = {
  name: string;
  description: string;
  access_policy: CollectionAccessPolicy;
  is_dynamic: boolean;
  rule_schema: DynamicRuleSet;
};

export const DEFAULT_FORM: CollectionFormState = {
  name: "",
  description: "",
  access_policy: "org_wide",
  is_dynamic: false,
  rule_schema: {
    logic: "and",
    conditions: [{ field: "file_type", operator: "eq", value: "pdf" }],
  },
};

type CollectionFormErrors = { name?: string };

function validateCollectionForm(
  form: CollectionFormState,
  msgs: { nameRequired: string; nameTooLong: string },
): CollectionFormErrors {
  const errors: CollectionFormErrors = {};
  if (!form.name.trim()) errors.name = msgs.nameRequired;
  else if (form.name.trim().length > 120) errors.name = msgs.nameTooLong;
  return errors;
}

export function CollectionDialog({
  title,
  initial,
  saving,
  saveError,
  onSave,
  onClose,
}: {
  title: string;
  initial: CollectionFormState;
  saving: boolean;
  saveError: string | null;
  onSave: (form: CollectionFormState) => void;
  onClose: () => void;
}) {
  const tc = useTranslations("collections.page");
  const [form, setForm] = useState<CollectionFormState>(initial);
  const [fieldErrors, setFieldErrors] = useState<CollectionFormErrors>({});
  const nameRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateCollectionForm(form, {
      nameRequired: tc("errorNameRequired"),
      nameTooLong: tc("errorNameTooLong"),
    });
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    onSave(form);
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            {tc("cancel")}
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tc("fieldNameLabel")} <span className="text-rose-600">*</span>
            </label>
            <input
              ref={nameRef}
              type="text"
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              maxLength={120}
              placeholder={tc("fieldNamePlaceholder")}
              className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-3 text-sm font-medium text-[#2a2640] outline-none placeholder:font-normal placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
            />
            {fieldErrors.name ? (
              <p className="mt-1 text-xs text-rose-700">{fieldErrors.name}</p>
            ) : null}
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tc("fieldDescLabel")}
            </label>
            <textarea
              value={form.description}
              onChange={(e) =>
                setForm((p) => ({ ...p, description: e.target.value }))
              }
              rows={3}
              maxLength={500}
              placeholder={tc("fieldDescPlaceholder")}
              className="w-full rounded-xl border border-[#d2cee6] bg-white px-3 py-2 text-sm font-medium text-[#2a2640] outline-none placeholder:font-normal placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tc("fieldAccessPolicyLabel")}
            </label>
            <select
              value={form.access_policy}
              onChange={(e) =>
                setForm((p) => ({
                  ...p,
                  access_policy: e.target.value as CollectionAccessPolicy,
                }))
              }
              className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            >
              <option value="org_wide">{tc("policyOptOrgWide")}</option>
              <option value="admin_only">{tc("policyLabelAdminOnly")}</option>
              <option value="selected_roles">
                {tc("policyLabelSelectedRoles")}
              </option>
              <option value="selected_members">
                {tc("policyLabelSelectedMembers")}
              </option>
            </select>
            <p className="mt-1 text-xs text-[#7a768f]">
              {accessPolicyDescription(form.access_policy, tc)}
            </p>
          </div>

          {/* Dynamic toggle */}
          <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={form.is_dynamic}
                onChange={(e) =>
                  setForm((p) => ({ ...p, is_dynamic: e.target.checked }))
                }
                className="accent-[#3525cd]"
              />
              <div>
                <p className="text-sm font-semibold text-[#2a2640]">
                  Dynamic collection
                </p>
                <p className="text-[11px] text-[#6a6780]">
                  Membership is automatically updated based on document metadata
                  rules.
                </p>
              </div>
            </label>
            {form.is_dynamic ? (
              <div className="mt-3 border-t border-[#e4e1ee] pt-3">
                <DynamicRuleBuilder
                  collectionId={null}
                  value={form.rule_schema}
                  onChange={(next) =>
                    setForm((p) => ({ ...p, rule_schema: next }))
                  }
                />
              </div>
            ) : null}
          </div>

          {saveError ? (
            <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {saveError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
            >
              {tc("cancel")}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? tc("saving") : tc("save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
