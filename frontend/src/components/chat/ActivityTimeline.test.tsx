import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ActivityTimeline } from "@/components/chat/ActivityTimeline";
import type { ActivityTimelineStep } from "@/lib/chat-websocket";

function makeStep(
  overrides: Partial<ActivityTimelineStep> & { stepKey: string; label: string },
): ActivityTimelineStep {
  return {
    sequence: 1,
    state: "success",
    detail: null,
    durationMs: null,
    ...overrides,
  };
}

describe("ActivityTimeline", () => {
  it("renders nothing when steps array is empty", () => {
    const { container } = render(<ActivityTimeline steps={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when all steps are skipped", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({ stepKey: "checking_sources", label: "Checking accessible sources", state: "skipped" }),
      makeStep({ stepKey: "searching_documents", label: "Searching knowledge base", state: "skipped", sequence: 2 }),
    ];
    const { container } = render(<ActivityTimeline steps={steps} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders visible non-skipped steps", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({ stepKey: "understanding_question", label: "Understanding your question", state: "success", sequence: 1 }),
      makeStep({ stepKey: "drafting_answer", label: "Drafting answer", state: "running", sequence: 2 }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("Understanding your question")).toBeInTheDocument();
    expect(screen.getByText("Drafting answer")).toBeInTheDocument();
  });

  it("filters out skipped steps while rendering others", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({ stepKey: "understanding_question", label: "Understanding your question", state: "success", sequence: 1 }),
      makeStep({ stepKey: "reranking_evidence", label: "Ranking evidence by relevance", state: "skipped", sequence: 2 }),
      makeStep({ stepKey: "drafting_answer", label: "Drafting answer", state: "running", sequence: 3 }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("Understanding your question")).toBeInTheDocument();
    expect(screen.queryByText("Ranking evidence by relevance")).not.toBeInTheDocument();
    expect(screen.getByText("Drafting answer")).toBeInTheDocument();
  });

  it("shows detail text when provided", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({
        stepKey: "searching_documents",
        label: "Searching knowledge base",
        state: "success",
        detail: "Found 8 relevant passages",
      }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("Found 8 relevant passages")).toBeInTheDocument();
  });

  it("shows duration for success steps", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({
        stepKey: "searching_documents",
        label: "Searching knowledge base",
        state: "success",
        durationMs: 342,
      }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("342ms")).toBeInTheDocument();
  });

  it("formats duration in seconds when >= 1000ms", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({
        stepKey: "drafting_answer",
        label: "Drafting answer",
        state: "success",
        durationMs: 2300,
      }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("2.3s")).toBeInTheDocument();
  });

  it("does not show duration for running steps", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({
        stepKey: "drafting_answer",
        label: "Drafting answer",
        state: "running",
        durationMs: 500,
      }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.queryByText("500ms")).not.toBeInTheDocument();
  });

  it("has accessible role and aria-live for live updates", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({ stepKey: "understanding_question", label: "Understanding your question", state: "running" }),
    ];
    render(<ActivityTimeline steps={steps} />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("renders warning state correctly", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({
        stepKey: "searching_documents",
        label: "Searching knowledge base",
        state: "warning",
        detail: "Limited relevant sources found",
      }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("Searching knowledge base")).toBeInTheDocument();
    expect(screen.getByText("Limited relevant sources found")).toBeInTheDocument();
  });

  it("renders failed state step", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({
        stepKey: "drafting_answer",
        label: "Drafting answer",
        state: "failed",
        detail: "Generation failed",
      }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText("Drafting answer")).toBeInTheDocument();
    expect(screen.getByText("Generation failed")).toBeInTheDocument();
  });

  it("renders multiple steps in order", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({ stepKey: "understanding_question", label: "Step One", state: "success", sequence: 1 }),
      makeStep({ stepKey: "checking_sources", label: "Step Two", state: "success", sequence: 2 }),
      makeStep({ stepKey: "drafting_answer", label: "Step Three", state: "running", sequence: 3 }),
    ];
    render(<ActivityTimeline steps={steps} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Step One");
    expect(items[1]).toHaveTextContent("Step Two");
    expect(items[2]).toHaveTextContent("Step Three");
  });

  it("step without detail renders no dash separator", () => {
    const steps: ActivityTimelineStep[] = [
      makeStep({ stepKey: "understanding_question", label: "Understanding your question", state: "success", detail: null }),
    ];
    render(<ActivityTimeline steps={steps} />);
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });
});
