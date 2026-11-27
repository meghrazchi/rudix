"use client";

import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { type AppRole } from "@/lib/auth-session";
import { SectionHeader } from "@/components/settings/security/securityShared";

// ── Role capability key maps ──────────────────────────────────────────────────

type RoleCapKey =
  | "documentAccess"
  | "collectionAccess"
  | "evaluationAccess"
  | "agenticAccess"
  | "mcpAccess"
  | "adminControls";

const ROLE_CAP_KEYS: RoleCapKey[] = [
  "documentAccess",
  "collectionAccess",
  "evaluationAccess",
  "agenticAccess",
  "mcpAccess",
  "adminControls",
];

const ROLE_CAP_LABEL_KEYS: Record<RoleCapKey, string> = {
  documentAccess: "capDocumentAccess",
  collectionAccess: "capCollectionAccess",
  evaluationAccess: "capEvaluationAccess",
  agenticAccess: "capAgenticAccess",
  mcpAccess: "capMcpAccess",
  adminControls: "capAdminControls",
};

const ROLE_CAP_DESC_KEYS: Record<AppRole, Record<RoleCapKey, string>> = {
  owner: {
    documentAccess: "ownerDocument",
    collectionAccess: "ownerCollection",
    evaluationAccess: "ownerEvaluation",
    agenticAccess: "ownerAgentic",
    mcpAccess: "ownerMcp",
    adminControls: "ownerAdmin",
  },
  admin: {
    documentAccess: "adminDocument",
    collectionAccess: "adminCollection",
    evaluationAccess: "adminEvaluation",
    agenticAccess: "adminAgentic",
    mcpAccess: "adminMcp",
    adminControls: "adminAdminControls",
  },
  member: {
    documentAccess: "memberDocument",
    collectionAccess: "memberCollection",
    evaluationAccess: "memberEvaluation",
    agenticAccess: "memberAgentic",
    mcpAccess: "memberMcp",
    adminControls: "memberAdmin",
  },
  viewer: {
    documentAccess: "viewerDocument",
    collectionAccess: "viewerCollection",
    evaluationAccess: "viewerEvaluation",
    agenticAccess: "viewerAgentic",
    mcpAccess: "viewerMcp",
    adminControls: "viewerAdmin",
  },
  reviewer: {
    documentAccess: "reviewerDocument",
    collectionAccess: "reviewerCollection",
    evaluationAccess: "reviewerEvaluation",
    agenticAccess: "reviewerAgentic",
    mcpAccess: "reviewerMcp",
    adminControls: "reviewerAdmin",
  },
  developer: {
    documentAccess: "developerDocument",
    collectionAccess: "developerCollection",
    evaluationAccess: "developerEvaluation",
    agenticAccess: "developerAgentic",
    mcpAccess: "developerMcp",
    adminControls: "developerAdmin",
  },
  security_admin: {
    documentAccess: "securityAdminDocument",
    collectionAccess: "securityAdminCollection",
    evaluationAccess: "securityAdminEvaluation",
    agenticAccess: "securityAdminAgentic",
    mcpAccess: "securityAdminMcp",
    adminControls: "securityAdminAdminControls",
  },
  billing_admin: {
    documentAccess: "billingAdminDocument",
    collectionAccess: "billingAdminCollection",
    evaluationAccess: "billingAdminEvaluation",
    agenticAccess: "billingAdminAgentic",
    mcpAccess: "billingAdminMcp",
    adminControls: "billingAdminAdminControls",
  },
};

export function RoleAccessSection({ role }: { role: AppRole | null }) {
  const t = useTranslations("settings.security");

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Role and access policy section"
    >
      <SectionHeader icon={ShieldCheck} title={t("rolePolicy.title")} />

      <div className="mb-4 flex items-center gap-3">
        <span className="text-sm text-[#464555]">
          {t("rolePolicy.currentRole")}
        </span>
        <span className="rounded-full bg-[#e2dfff] px-3 py-1 text-sm font-bold text-[#3525cd] capitalize">
          {role ?? t("unknown")}
        </span>
      </div>

      {role ? (
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {ROLE_CAP_KEYS.map((capKey) => (
            <div
              key={capKey}
              className="flex flex-col rounded-lg border border-[#ebe8f7] bg-[#f5f2ff]/40 px-4 py-3"
            >
              <dt className="text-xs font-semibold tracking-widest text-[#464555] uppercase">
                {t(`rolePolicy.${ROLE_CAP_LABEL_KEYS[capKey]}`)}
              </dt>
              <dd className="mt-1 text-sm text-[#1b1b24]">
                {t(`rolePolicy.${ROLE_CAP_DESC_KEYS[role][capKey]}`)}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-[#777587]">{t("rolePolicy.unavailable")}</p>
      )}
    </section>
  );
}
