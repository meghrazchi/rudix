"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listChatSessions } from "@/lib/api/chat";
import { listDocuments } from "@/lib/api/documents";
import {
  getOnboardingConfig,
  loadSampleDataset,
} from "@/lib/api/onboarding";
import { queryKeys } from "@/lib/api/query";
import type { AuthenticatedSession } from "@/lib/auth-session";
import {
  type AutoDetectedCompletions,
  type OnboardingState,
  type OnboardingStepId,
  ONBOARDING_QUERY_KEY,
  applyServerReset,
  isStepComplete,
  resolveVisibleSteps,
  writeOnboardingState,
} from "@/lib/onboarding";
import { trackOnboardingEvent } from "@/lib/analytics";

type OnboardingChecklistProps = {
  session: AuthenticatedSession;
  state: OnboardingState;
  onStateChange: (next: OnboardingState) => void;
  onDismiss: () => void;
};

export function OnboardingChecklist({
  session,
  state,
  onStateChange,
  onDismiss,
}: OnboardingChecklistProps) {
  const [expanded, setExpanded] = useState(true);
  const [tourRunning, setTourRunning] = useState(false);

  const queryClient = useQueryClient();

  const configQuery = useQuery({
    queryKey: ONBOARDING_QUERY_KEY,
    queryFn: getOnboardingConfig,
    staleTime: 5 * 60_000,
    enabled: session.role === "owner" || session.role === "admin",
  });

  // Apply server reset when admin has triggered one after client last saw it.
  useEffect(() => {
    if (!configQuery.data) return;
    const resetAt = configQuery.data.reset_at;
    const next = applyServerReset(state, resetAt);
    if (next === state) return;
    onStateChange(next);
    writeOnboardingState(session.userId, next);
  }, [configQuery.data, state, onStateChange, session.userId]);

  const sampleDocsEnabled =
    (session.role === "owner" || session.role === "admin") &&
    (configQuery.data?.sample_docs_enabled ?? false);

  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list({ scope: "onboarding", limit: 200 }),
    queryFn: () => listDocuments({ limit: 200 }),
    staleTime: 60_000,
  });

  const chatQuery = useQuery({
    queryKey: ["onboarding", "chat-sessions", { limit: 1 }],
    queryFn: () => listChatSessions({ limit: 1, offset: 0 }),
    staleTime: 60_000,
  });

  const autoDetected: AutoDetectedCompletions = useMemo(
    () => ({
      hasOrganization: Boolean(session.organizationId),
      hasDocuments: (documentsQuery.data?.total ?? 0) > 0,
      hasIndexedDocuments: (documentsQuery.data?.items ?? []).some(
        (doc) => doc.status === "indexed",
      ),
      hasChatSessions: (chatQuery.data?.total ?? 0) > 0,
    }),
    [session.organizationId, documentsQuery.data, chatQuery.data],
  );

  const visibleSteps = useMemo(
    () => resolveVisibleSteps(session.role),
    [session.role],
  );

  const completedCount = useMemo(
    () =>
      visibleSteps.filter((step) =>
        isStepComplete(step.id, autoDetected, state.manuallyCompleted),
      ).length,
    [visibleSteps, autoDetected, state.manuallyCompleted],
  );

  const allComplete = completedCount === visibleSteps.length;

  const progress =
    visibleSteps.length > 0
      ? Math.round((completedCount / visibleSteps.length) * 100)
      : 0;

  const sampleMutation = useMutation({
    mutationFn: loadSampleDataset,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.list({ scope: "onboarding", limit: 200 }),
      });
      trackOnboardingEvent("onboarding_sample_docs_loaded", {
        organization_id: session.organizationId ?? "",
      });
    },
  });

  function markManualDone(stepId: OnboardingStepId) {
    const next: OnboardingState = {
      ...state,
      manuallyCompleted: [
        ...state.manuallyCompleted.filter((id) => id !== stepId),
        stepId,
      ],
    };
    onStateChange(next);
    writeOnboardingState(session.userId, next);
    trackOnboardingEvent("onboarding_step_complete", {
      step_id: stepId,
      method: "manual",
    });
  }

  function handleDismiss() {
    const next: OnboardingState = { ...state, dismissed: true };
    onStateChange(next);
    writeOnboardingState(session.userId, next);
    onDismiss();
    trackOnboardingEvent("onboarding_dismissed", {
      progress_pct: progress,
      completed_steps: completedCount,
      total_steps: visibleSteps.length,
    });
  }

  const launchTour = useCallback(async () => {
    if (typeof window === "undefined" || tourRunning) return;

    try {
      setTourRunning(true);
      trackOnboardingEvent("onboarding_tour_started");
      const { default: introJs } = await import("intro.js");

      const tour = introJs.tour();

      tour.setOptions({
        steps: [
          {
            title: "Welcome to Rudix",
            intro:
              "Let us walk you through the key parts of your enterprise RAG workspace.",
          },
          {
            element:
              document.querySelector<HTMLElement>(
                '[data-onboarding="nav-documents"]',
              ) ?? undefined,
            title: "Knowledge base",
            intro:
              "Upload PDFs, DOCX files, and more. Rudix chunks and indexes them automatically for AI-powered search.",
          },
          {
            element:
              document.querySelector<HTMLElement>(
                '[data-onboarding="nav-chat"]',
              ) ?? undefined,
            title: "Chat interface",
            intro:
              "Ask questions and get grounded answers with citations back to the exact source passages in your documents.",
          },
          {
            element:
              document.querySelector<HTMLElement>(
                '[data-onboarding="nav-settings"]',
              ) ?? undefined,
            title: "Settings",
            intro:
              "Manage your team, configure security policies, and review billing from the settings page.",
          },
          {
            element:
              document.querySelector<HTMLElement>(
                '[data-onboarding="checklist-trigger"]',
              ) ?? undefined,
            title: "Your progress",
            intro:
              "Reopen this checklist anytime from the Help menu to track your setup progress.",
          },
        ],
        nextLabel: "Next →",
        prevLabel: "← Back",
        doneLabel: "Done",
        skipLabel: "Skip tour",
        showProgress: true,
        showBullets: false,
        exitOnOverlayClick: true,
        disableInteraction: false,
        overlayOpacity: 0.5,
      });

      tour.onComplete(() => {
        const next: OnboardingState = { ...state, tourSeen: true };
        onStateChange(next);
        writeOnboardingState(session.userId, next);
        setTourRunning(false);
        trackOnboardingEvent("onboarding_tour_completed");
      });

      tour.onExit(() => {
        setTourRunning(false);
      });

      await tour.start();
    } catch {
      setTourRunning(false);
    }
  }, [tourRunning, state, onStateChange, session.userId]);

  const hasNoDocuments = (documentsQuery.data?.total ?? 0) === 0;

  if (!expanded) {
    return (
      <button
        type="button"
        data-onboarding="checklist-trigger"
        onClick={() => setExpanded(true)}
        aria-label="Open getting started checklist"
        className="flex w-full items-center gap-3 rounded-2xl border border-[#d7d4e8] bg-white px-4 py-3 shadow-xl transition hover:bg-[#f5f3ff]"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#ece9ff]">
          <ChecklistSvg />
        </span>
        <div className="min-w-0 flex-1 text-left">
          <p className="text-sm font-bold text-[#2a2640]">Getting started</p>
          <p className="text-xs text-[#68647b]">
            {completedCount} of {visibleSteps.length} steps done
          </p>
        </div>
        <ChevronUpSvg className="h-4 w-4 text-[#3525cd]" />
      </button>
    );
  }

  return (
    <div
      role="region"
      aria-label="Getting started checklist"
      className="overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
    >
      <div className="flex items-center justify-between gap-2 bg-[#3525cd] px-4 py-3">
        <div>
          <p className="text-sm font-bold text-white">Getting started</p>
          <p className="text-xs text-[#c4bcff]">
            {allComplete
              ? "All steps complete!"
              : `${completedCount} of ${visibleSteps.length} steps done`}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="rounded p-1 text-[#c4bcff] transition hover:bg-[#4535e0] hover:text-white"
            aria-label="Collapse checklist"
          >
            <ChevronDownSvg className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={handleDismiss}
            className="rounded p-1 text-[#c4bcff] transition hover:bg-[#4535e0] hover:text-white"
            aria-label="Dismiss getting started checklist (reopen from Help menu)"
            title="Dismiss — reopen from Help menu"
          >
            <CloseSvg className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div
        className="h-1.5 w-full bg-[#ece9ff]"
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Setup ${progress}% complete`}
      >
        <div
          className="h-full bg-[#3525cd] transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      <ol
        className="max-h-[360px] overflow-auto px-3 py-2"
        aria-label="Setup steps"
      >
        {visibleSteps.map((step) => {
          const done = isStepComplete(
            step.id,
            autoDetected,
            state.manuallyCompleted,
          );

          const showSampleDocs =
            step.id === "upload_document" &&
            !done &&
            sampleDocsEnabled &&
            hasNoDocuments;

          return (
            <li
              key={step.id}
              className={`my-1 flex items-start gap-3 rounded-xl px-3 py-2.5 ${done ? "" : "hover:bg-[#faf9ff]"}`}
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
                  done
                    ? "border-[#3525cd] bg-[#3525cd]"
                    : "border-[#d7d4e8] bg-white"
                }`}
              >
                {done ? <CheckSvg className="h-3 w-3 text-white" /> : null}
              </span>

              <div className="min-w-0 flex-1">
                <p
                  className={`text-sm font-semibold ${done ? "text-[#7a7693] line-through" : "text-[#2a2640]"}`}
                >
                  {step.title}
                  {done ? <span className="sr-only"> (complete)</span> : null}
                </p>
                <p className="mt-0.5 text-xs text-[#68647b]">
                  {step.description}
                </p>
                {!done ? (
                  <div className="mt-1.5 flex flex-wrap items-center gap-3">
                    {step.href ? (
                      <Link
                        href={step.href}
                        className="text-xs font-semibold text-[#3525cd] hover:underline"
                      >
                        {step.actionLabel} →
                      </Link>
                    ) : null}
                    {showSampleDocs ? (
                      <button
                        type="button"
                        onClick={() => sampleMutation.mutate()}
                        disabled={sampleMutation.isPending}
                        className="text-xs font-semibold text-[#7c3aed] hover:underline disabled:opacity-50"
                      >
                        {sampleMutation.isPending
                          ? "Loading…"
                          : "Load sample dataset"}
                      </button>
                    ) : null}
                    {!step.autoDetectable ? (
                      <button
                        type="button"
                        onClick={() => markManualDone(step.id)}
                        className="text-xs text-[#7a7693] hover:text-[#3525cd] hover:underline"
                      >
                        Mark done
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      <div className="border-t border-[#ece9ff] px-3 py-2.5">
        <button
          type="button"
          onClick={() => void launchTour()}
          disabled={tourRunning}
          className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-xs font-semibold text-[#3525cd] transition hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state.tourSeen ? "Replay guided tour" : "Start guided tour"}
        </button>
      </div>
    </div>
  );
}

function ChecklistSvg() {
  return (
    <svg
      className="h-4 w-4 text-[#3525cd]"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  );
}

function CheckSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

function ChevronUpSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M18 15l-6-6-6 6" />
    </svg>
  );
}

function ChevronDownSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function CloseSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}
