"use client";

import { z } from "zod";
import { type TeamMember } from "@/lib/api/team";
import { type OrganizationInvitation } from "@/lib/api/team-invitations";

export const PAGE_SIZE = 20;

export const inviteSchema = z.object({
  email: z.string().trim().min(1).email(),
  name: z.string().trim().max(255).optional(),
  role: z.enum([
    "admin",
    "member",
    "viewer",
    "reviewer",
    "developer",
    "security_admin",
    "billing_admin",
  ]),
});
export type InviteValues = z.infer<typeof inviteSchema>;

export type ConfirmAction =
  | { kind: "remove"; member: TeamMember }
  | { kind: "deactivate"; member: TeamMember }
  | { kind: "revoke"; invitation: OrganizationInvitation };

export function roleBadgeClass(role: string): string {
  if (role === "owner")
    return "inline-flex rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-semibold text-violet-800";
  if (role === "admin")
    return "inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-800";
  if (role === "member")
    return "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800";
  if (role === "viewer")
    return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700";
  return "inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800";
}

export function statusBadgeClass(s: string): string {
  if (s === "active")
    return "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800";
  if (s === "invited")
    return "inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800";
  if (s === "disabled" || s === "suspended")
    return "inline-flex rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-800";
  return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700";
}

export function formatDate(
  v: string | null | undefined,
  locale: string,
): string {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString(locale);
  } catch {
    return v;
  }
}
