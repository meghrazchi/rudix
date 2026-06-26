"use client";

import type { ActivityTimelineStep } from "@/lib/chat-websocket";

type ActivityTimelineProps = {
  steps: ActivityTimelineStep[];
};

const STATE_ICON: Record<ActivityTimelineStep["state"], string> = {
  pending: "radio_button_unchecked",
  running: "pending",
  success: "check_circle",
  warning: "warning",
  failed: "cancel",
  skipped: "remove_circle",
};

const STATE_COLOR: Record<ActivityTimelineStep["state"], string> = {
  pending: "text-[#9896a8]",
  running: "text-[#3525cd]",
  success: "text-[#1a8a4a]",
  warning: "text-[#b45309]",
  failed: "text-[#dc2626]",
  skipped: "text-[#9896a8]",
};

const ICON_FILL: Record<ActivityTimelineStep["state"], boolean> = {
  pending: false,
  running: true,
  success: true,
  warning: true,
  failed: true,
  skipped: true,
};

export function ActivityTimeline({ steps }: ActivityTimelineProps) {
  if (steps.length === 0) return null;

  const visibleSteps = steps.filter((s) => s.state !== "skipped");

  if (visibleSteps.length === 0) return null;

  return (
    <div
      className="mb-3 rounded-lg border border-[#e2dff1] bg-[#f9f8ff] px-3 py-2"
      aria-label="Answer generation timeline"
      role="status"
      aria-live="polite"
    >
      <ul className="space-y-1" aria-label="Activity steps">
        {visibleSteps.map((step) => (
          <ActivityStep key={step.stepKey} step={step} />
        ))}
      </ul>
    </div>
  );
}

function ActivityStep({ step }: { step: ActivityTimelineStep }) {
  const iconName = STATE_ICON[step.state];
  const colorClass = STATE_COLOR[step.state];
  const fill = ICON_FILL[step.state];
  const isRunning = step.state === "running";

  return (
    <li className="flex items-center gap-2 text-sm">
      <span
        className={`material-symbols-outlined shrink-0 text-[16px] ${colorClass} ${isRunning ? "animate-pulse" : ""}`}
        aria-hidden="true"
        style={fill ? { fontVariationSettings: "'FILL' 1" } : undefined}
      >
        {iconName}
      </span>
      <span
        className={`font-medium ${isRunning ? "text-[#464555]" : step.state === "skipped" || step.state === "pending" ? "text-[#9896a8]" : "text-[#2d2c3e]"}`}
      >
        {step.label}
      </span>
      {step.detail && (
        <span className="text-[#6b6a7d]">&mdash; {step.detail}</span>
      )}
      {step.durationMs != null && step.state === "success" && (
        <span className="ml-auto shrink-0 text-xs text-[#9896a8]">
          {step.durationMs < 1000
            ? `${step.durationMs}ms`
            : `${(step.durationMs / 1000).toFixed(1)}s`}
        </span>
      )}
    </li>
  );
}
