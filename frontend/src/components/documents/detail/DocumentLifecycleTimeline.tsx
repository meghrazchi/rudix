import {
  formatDate,
  timelineStepClass,
  timelineStepGlyph,
} from "@/components/documents/detail/detail-format";
import type { TimelineStep } from "@/components/documents/detail/detail-lifecycle";
import type { DocumentDetailTranslator } from "@/components/documents/detail/useDocumentDetailMutations";

/** Lifecycle timeline side panel. */
export function DocumentLifecycleTimeline({
  td,
  lifecycle,
}: {
  td: DocumentDetailTranslator;
  lifecycle: TimelineStep[];
}) {
  return (
    <section className="rounded-xl border border-[#e4e1f2] bg-white p-4 shadow-sm lg:col-span-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {td("lifecycleTitle")}
      </h3>
      <ol className="relative space-y-3">
        <div className="absolute start-[11px] top-1 bottom-1 w-[2px] bg-[#e1e0eb]" />
        {lifecycle.map((step) => (
          <li key={step.key} className="relative z-10 flex items-start gap-3">
            <span
              className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[12px] font-bold ${timelineStepClass(step.state)}`}
            >
              {timelineStepGlyph(step.state)}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold text-[#2a2640]">
                  {step.label}
                </p>
                <p className="text-[11px] text-[#68647b]">
                  {step.timestamp ? formatDate(step.timestamp) : "-"}
                </p>
              </div>
              <p className="mt-0.5 text-xs text-[#5f5a74]">
                {step.description}
              </p>
              {step.logs.slice(0, 1).map((line, index) => (
                <p
                  key={`${step.key}-timeline-${index}`}
                  className="mt-1 text-xs break-words text-[#4c4970]"
                >
                  {line}
                </p>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
