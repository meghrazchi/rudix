"use client";

import Link from "next/link";
import { sanitizeRequestId } from "@/lib/forbidden";
import {
  formatTimestamp,
  getActorLabel,
} from "@/components/admin/audit-logs/auditShared";
import { useAuditLogsController } from "@/components/admin/audit-logs/useAuditLogsController";

export function AuditEventDrawer({
  ctl,
}: {
  ctl: ReturnType<typeof useAuditLogsController>;
}) {
  const {
    t,
    drawerTop,
    selectedEvent,
    eventDrawerRef,
    closeSelectedEvent,
    selectedSanitizedMetadata,
    selectedBeforeAfter,
    selectedRelatedLinks,
  } = ctl;

  return (
    <>
      {selectedEvent ? (
        <>
          <button
            type="button"
            aria-label={t("closeEventDetails")}
            onClick={closeSelectedEvent}
            className="absolute inset-0 z-10 bg-[#17172a]/15 xl:bg-transparent"
          />
          <aside
            ref={eventDrawerRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="audit-event-details-title"
            className="absolute right-0 z-20 max-h-[min(78vh,720px)] w-full max-w-[430px] overflow-y-auto rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-2xl"
            style={{ top: `${drawerTop}px` }}
          >
            <>
              <div className="mb-4 flex items-start justify-between gap-3 border-b border-[#e4e1ee] pb-3">
                <div>
                  <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("eventDetails")}
                  </p>
                  <h3
                    id="audit-event-details-title"
                    className="mt-1 text-base font-semibold text-[#1b1b24]"
                  >
                    {selectedEvent.action}
                  </h3>
                </div>
                <button
                  type="button"
                  data-overlay-autofocus="true"
                  onClick={closeSelectedEvent}
                  className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#38485d] hover:bg-[#f5f2ff]"
                >
                  {t("close")}
                </button>
              </div>

              <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
                {t("verifiedRecord")}
              </div>

              <dl className="grid gap-2 text-sm">
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("requestId")}
                  </dt>
                  <dd className="font-mono text-xs text-[#302f39]">
                    {sanitizeRequestId(selectedEvent.request_id) ?? "-"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("organization")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {selectedEvent.organization_id}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("actor")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {getActorLabel(selectedEvent, t("system"))}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("resultSeverity")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {(selectedEvent.result ?? "unknown").toUpperCase()} /{" "}
                    {selectedEvent.severity ?? "-"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("ipSession")}
                  </dt>
                  <dd className="font-mono text-xs text-[#302f39]">
                    {selectedEvent.ip_address ?? "-"} /{" "}
                    {selectedEvent.session_id ?? "-"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("timestamp")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {formatTimestamp(selectedEvent.created_at)}
                  </dd>
                </div>
              </dl>

              {selectedRelatedLinks.length > 0 ? (
                <div className="mt-5">
                  <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("relatedLinks")}
                  </h4>
                  <div className="mt-2 grid gap-2">
                    {selectedRelatedLinks.map((link) => (
                      <Link
                        key={`${link.href}:${link.label}`}
                        href={link.href}
                        className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
                      >
                        {link.label}
                      </Link>
                    ))}
                  </div>
                </div>
              ) : null}

              {selectedBeforeAfter &&
              (selectedBeforeAfter.before != null ||
                selectedBeforeAfter.after != null ||
                selectedBeforeAfter.changedFields.length > 0) ? (
                <div className="mt-5 space-y-3">
                  <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("beforeAfterSummary")}
                  </h4>
                  {selectedBeforeAfter.changedFields.length > 0 ? (
                    <div>
                      <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                        {t("changedFields")}
                      </p>
                      <p className="text-sm text-[#302f39]">
                        {selectedBeforeAfter.changedFields.join(", ")}
                      </p>
                    </div>
                  ) : null}
                  {selectedBeforeAfter.before != null ? (
                    <div>
                      <p className="text-[10px] font-semibold tracking-[0.08em] text-rose-700 uppercase">
                        {t("before")}
                      </p>
                      <pre className="mt-1 overflow-x-auto rounded-lg bg-[#1f1f29] p-3 font-mono text-xs text-rose-100">
                        {JSON.stringify(selectedBeforeAfter.before, null, 2)}
                      </pre>
                    </div>
                  ) : null}
                  {selectedBeforeAfter.after != null ? (
                    <div>
                      <p className="text-[10px] font-semibold tracking-[0.08em] text-emerald-700 uppercase">
                        {t("after")}
                      </p>
                      <pre className="mt-1 overflow-x-auto rounded-lg bg-[#1f1f29] p-3 font-mono text-xs text-emerald-100">
                        {JSON.stringify(selectedBeforeAfter.after, null, 2)}
                      </pre>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="mt-5">
                <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  {t("sanitizedMetadata")}
                </h4>
                <pre className="mt-2 overflow-x-auto rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3 text-xs text-[#302f39]">
                  {JSON.stringify(selectedSanitizedMetadata, null, 2)}
                </pre>
              </div>
            </>
          </aside>
        </>
      ) : null}
    </>
  );
}
