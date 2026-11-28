"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { type TeamMember, type TeamInviteRole } from "@/lib/api/team";
import { roleBadgeClass } from "@/components/admin/team/teamShared";

export function RoleChangeRow({
  member,
  isDisabled,
  onRoleChange,
}: {
  member: TeamMember;
  isDisabled: boolean;
  onRoleChange: (memberId: string, role: TeamInviteRole) => void;
}) {
  return (
    <RoleChangeRowEditor
      key={`${member.member_id}:${member.role}`}
      member={member}
      isDisabled={isDisabled}
      onRoleChange={onRoleChange}
    />
  );
}

export function RoleChangeRowEditor({
  member,
  isDisabled,
  onRoleChange,
}: {
  member: TeamMember;
  isDisabled: boolean;
  onRoleChange: (memberId: string, role: TeamInviteRole) => void;
}) {
  const t = useTranslations("adminTeam");
  const [draft, setDraft] = useState<TeamInviteRole>(
    member.role as TeamInviteRole,
  );
  const changed = draft !== member.role;

  if (member.role === "owner") {
    return (
      <span className={roleBadgeClass(member.role)}>{t("roles.owner")}</span>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <select
        aria-label={t("roleFor", { email: member.email })}
        disabled={isDisabled}
        value={draft}
        onChange={(e) => setDraft(e.target.value as TeamInviteRole)}
        className="h-7 rounded border border-[#d2cee6] px-1.5 text-xs text-[#2f2a46] disabled:opacity-60"
      >
        <option value="admin">{t("roles.admin")}</option>
        <option value="member">{t("roles.member")}</option>
        <option value="viewer">{t("roles.viewer")}</option>
        <option value="reviewer">{t("roles.reviewer")}</option>
        <option value="developer">{t("roles.developer")}</option>
        <option value="security_admin">{t("roles.securityAdmin")}</option>
        <option value="billing_admin">{t("roles.billingAdmin")}</option>
      </select>
      {changed && (
        <button
          type="button"
          disabled={isDisabled}
          onClick={() => onRoleChange(member.member_id, draft)}
          className="rounded border border-[#3525cd] px-1.5 py-0.5 text-[11px] font-semibold text-[#3525cd] hover:bg-[#f0edf9] disabled:opacity-60"
        >
          {t("actions.changeRole")}
        </button>
      )}
    </div>
  );
}
