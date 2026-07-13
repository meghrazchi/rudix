import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ChartCard,
  DetailDrawer,
  KpiCard,
  PartialDataState,
  RecommendedActionCard,
  ReportDataTable,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

describe("report component library", () => {
  it("renders reusable headers, cards, tables, badges, and actions", () => {
    render(
      <>
        <ReportHeader title="Answer Quality" description="Quality trends" />
        <KpiCard label="Confidence" value="92%" />
        <ChartCard title="Trend">
          <span>chart</span>
        </ChartCard>
        <ReportDataTable
          caption="Metrics"
          columns={["Metric"]}
          rows={[["Grounding"]]}
        />
        <StatusBadge label="Healthy" tone="healthy" />
        <RecommendedActionCard
          title="Review gaps"
          description="Three topics need sources."
        />
      </>,
    );
    expect(
      screen.getByRole("heading", { name: "Answer Quality" }),
    ).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Metrics" })).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
  });

  it("renders empty, loading, error, partial, and no-permission states", () => {
    render(
      <>
        <EmptyState title="No report data" />
        <LoadingState title="Loading report" />
        <ErrorState title="Report failed" description="Try again." />
        <PartialDataState message="One connector is delayed." />
        <ForbiddenState title="Report unavailable" />
      </>,
    );
    expect(screen.getByLabelText("Empty state")).toBeInTheDocument();
    expect(screen.getByLabelText("Loading state")).toBeInTheDocument();
    expect(screen.getByLabelText("Error state")).toBeInTheDocument();
    expect(screen.getByText(/One connector is delayed/)).toBeInTheDocument();
    expect(screen.getByLabelText("Forbidden state")).toBeInTheDocument();
  });

  it("renders and closes the detail drawer", () => {
    const close = vi.fn();
    render(
      <DetailDrawer title="Metric details" open onClose={close}>
        Details
      </DetailDrawer>,
    );
    expect(
      screen.getByRole("dialog", { name: "Metric details" }),
    ).toBeInTheDocument();
    screen.getByRole("button", { name: "Close details" }).click();
    expect(close).toHaveBeenCalledOnce();
  });

  it("uses responsive report layout contracts", () => {
    const { container } = render(
      <ReportHeader title="Usage" description="Adoption trends" />,
    );
    expect(container.querySelector("header")).toHaveClass("sm:flex-row");
    expect(screen.getByRole("heading", { name: "Usage" })).toHaveClass(
      "sm:text-3xl",
    );
  });
});
