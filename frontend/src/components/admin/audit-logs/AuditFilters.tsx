"use client";

import {
  DASHBOARD_RANGE_PRESETS,
  type DashboardRangePreset,
} from "@/lib/dashboard";
import { type AppliedFilters } from "@/components/admin/audit-logs/auditShared";
import { useAuditLogsController } from "@/components/admin/audit-logs/useAuditLogsController";

export function AuditFilters({
  ctl,
}: {
  ctl: ReturnType<typeof useAuditLogsController>;
}) {
  const {
    t,
    rangePreset,
    setRangePreset,
    organizationIdInput,
    setOrganizationIdInput,
    actorInput,
    setActorInput,
    actionInput,
    setActionInput,
    entityInput,
    setEntityInput,
    resourceIdInput,
    setResourceIdInput,
    documentIdInput,
    setDocumentIdInput,
    collectionIdInput,
    setCollectionIdInput,
    ipAddressInput,
    setIpAddressInput,
    sessionIdInput,
    setSessionIdInput,
    requestIdInput,
    setRequestIdInput,
    resultFilterInput,
    setResultFilterInput,
    severityInput,
    setSeverityInput,
    searchInput,
    setSearchInput,
    showAdvancedFilters,
    setShowAdvancedFilters,
    setOffset,
    applyFilters,
    clearFilters,
  } = ctl;

  return (
    <section className="rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
      <form className="space-y-3" onSubmit={applyFilters}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[240px] flex-1 space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("searchActor")}
            </span>
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder={t("searchPlaceholder")}
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>

          <label className="w-[190px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("dateRange")}
            </span>
            <select
              value={rangePreset}
              onChange={(event) => {
                setOffset(0);
                setRangePreset(event.target.value as DashboardRangePreset);
              }}
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              {DASHBOARD_RANGE_PRESETS.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(`ranges.${option.value}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="w-[190px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("actionType")}
            </span>
            <select
              value={actionInput}
              onChange={(event) => setActionInput(event.target.value)}
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">{t("allActions")}</option>
              <option value="auth.login.succeeded">{t("login")}</option>
              <option value="document.upload.accepted">{t("upload")}</option>
              <option value="collection.policy.updated">
                {t("policyChange")}
              </option>
              <option value="chat.query.completed">{t("chatQuery")}</option>
            </select>
          </label>

          <label className="w-[170px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("severity")}
            </span>
            <select
              value={severityInput}
              onChange={(event) => setSeverityInput(event.target.value)}
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">{t("allLevels")}</option>
              <option value="info">{t("info")}</option>
              <option value="warning">{t("warning")}</option>
              <option value="critical">{t("critical")}</option>
            </select>
          </label>

          <button
            type="button"
            onClick={() => setShowAdvancedFilters((current) => !current)}
            className="h-10 rounded-lg border border-[#c7c4d8] px-3 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff]"
          >
            {showAdvancedFilters ? t("hideAdvanced") : t("advancedFilters")}
          </button>
          <button
            type="submit"
            className="h-10 rounded-lg bg-[#3525cd] px-4 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8]"
          >
            {t("applyFilters")}
          </button>
          <button
            type="button"
            onClick={clearFilters}
            className="h-10 px-2 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:underline"
          >
            {t("clearFilters")}
          </button>
        </div>

        {showAdvancedFilters ? (
          <div className="grid gap-3 border-t border-[#e4e1ee] pt-3 sm:grid-cols-2 xl:grid-cols-4">
            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("organization")}
              <input
                value={organizationIdInput}
                onChange={(event) => setOrganizationIdInput(event.target.value)}
                placeholder={t("organizationPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("actor")}
              <input
                value={actorInput}
                onChange={(event) => setActorInput(event.target.value)}
                placeholder={t("actorPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("result")}
              <select
                aria-label={t("result")}
                value={resultFilterInput}
                onChange={(event) =>
                  setResultFilterInput(
                    event.target.value as AppliedFilters["result"],
                  )
                }
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                <option value="all">{t("allResults")}</option>
                <option value="success">{t("success")}</option>
                <option value="failure">{t("failure")}</option>
                <option value="unknown">{t("unknown")}</option>
              </select>
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("entity")}
              <input
                value={entityInput}
                onChange={(event) => setEntityInput(event.target.value)}
                placeholder={t("entityPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("resourceId")}
              <input
                value={resourceIdInput}
                onChange={(event) => setResourceIdInput(event.target.value)}
                placeholder={t("resourcePlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("documentId")}
              <input
                value={documentIdInput}
                onChange={(event) => setDocumentIdInput(event.target.value)}
                placeholder={t("documentPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("collectionId")}
              <input
                value={collectionIdInput}
                onChange={(event) => setCollectionIdInput(event.target.value)}
                placeholder={t("collectionPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("ipAddress")}
              <input
                value={ipAddressInput}
                onChange={(event) => setIpAddressInput(event.target.value)}
                placeholder={t("ipPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("sessionId")}
              <input
                value={sessionIdInput}
                onChange={(event) => setSessionIdInput(event.target.value)}
                placeholder={t("sessionPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("requestId")}
              <input
                value={requestIdInput}
                onChange={(event) => setRequestIdInput(event.target.value)}
                placeholder={t("requestPlaceholder")}
                className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>
          </div>
        ) : null}
      </form>
    </section>
  );
}
