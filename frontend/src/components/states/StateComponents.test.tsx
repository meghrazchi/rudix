import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { NetworkErrorState } from "@/components/states/NetworkErrorState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import { normalizeApiError } from "@/lib/api/errors";

describe("State components", () => {
  it("renders loading state", () => {
    render(
      <LoadingState title="Loading documents..." description="Please wait." />,
    );
    expect(screen.getByText("Loading documents...")).toBeInTheDocument();
    expect(screen.getByText("Please wait.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders loading state in compact mode", () => {
    render(<LoadingState compact title="Loading…" />);
    const section = screen.getByRole("status");
    expect(section).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders loading state with pulse indicator", () => {
    const { container } = render(<LoadingState title="Loading…" />);
    const pulse = container.querySelector(".animate-pulse");
    expect(pulse).not.toBeNull();
  });

  it("renders empty state with action", async () => {
    const onAction = vi.fn();
    render(
      <EmptyState
        title="No documents found"
        description="Upload a file to continue."
        action={
          <button type="button" onClick={onAction}>
            Upload
          </button>
        }
      />,
    );

    expect(screen.getByText("No documents found")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("renders empty state in compact mode without description or action", () => {
    render(<EmptyState compact title="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("renders conflict error state with trace id and retry", async () => {
    const onRetry = vi.fn();
    const error = normalizeApiError({
      status: 409,
      payload: {
        detail: "Conflict",
      },
      requestId: "trace-123",
    });

    render(<ErrorState error={error} onRetry={onRetry} />);
    expect(screen.getByText("Request conflict")).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders rate limit state through error wrapper", () => {
    const error = normalizeApiError({
      status: 429,
      payload: {
        detail: "Too many requests",
      },
      requestId: "trace-429",
    });

    render(<ErrorState error={error} />);
    expect(screen.getByText("Rate limit reached")).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
  });

  it("renders network error state through error wrapper for status 0", async () => {
    const onRetry = vi.fn();
    const error = normalizeApiError({
      status: 0,
      payload: null,
      requestId: null,
    });

    render(<ErrorState error={error} onRetry={onRetry} />);
    expect(screen.getByText("No connection")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders direct rate limit state", () => {
    render(<RateLimitState requestId="trace-rate-limit" />);
    expect(screen.getByText("Rate limit reached")).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
  });

  it("does not render retry button in error state when no onRetry provided", () => {
    const error = normalizeApiError({
      status: 500,
      payload: null,
      requestId: null,
    });
    render(<ErrorState error={error} />);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("renders error state with custom retry label", async () => {
    const onRetry = vi.fn();
    const error = normalizeApiError({
      status: 500,
      payload: null,
      requestId: null,
    });
    render(
      <ErrorState error={error} onRetry={onRetry} retryLabel="Try again" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders network error state standalone", async () => {
    const onRetry = vi.fn();
    render(<NetworkErrorState onRetry={onRetry} />);
    expect(screen.getByText("No connection")).toBeInTheDocument();
    expect(
      screen.getByText(/Check your network connection/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders network error state in compact mode without retry", () => {
    render(<NetworkErrorState compact />);
    expect(screen.getByText("No connection")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders skeleton block with default row count", () => {
    const { container } = render(<SkeletonBlock />);
    const pulseRows = container.querySelectorAll(".animate-pulse");
    expect(pulseRows.length).toBe(3);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders skeleton block with custom row count", () => {
    const { container } = render(<SkeletonBlock rows={5} />);
    const pulseRows = container.querySelectorAll(".animate-pulse");
    expect(pulseRows.length).toBe(5);
  });

  it("renders skeleton block in compact mode", () => {
    const { container } = render(<SkeletonBlock compact rows={2} />);
    const pulseRows = container.querySelectorAll(".animate-pulse");
    expect(pulseRows.length).toBe(2);
  });

  it("renders forbidden state with back link and no trace id", () => {
    render(
      <ForbiddenState
        title="Access denied"
        description="You cannot view this resource."
        backHref="/dashboard"
        backLabel="Go home"
      />,
    );
    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(
      screen.getByText("You cannot view this resource."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go home" })).toBeInTheDocument();
    expect(screen.queryByText("Trace ID:")).toBeNull();
  });

  it("renders forbidden state with trace id", () => {
    render(<ForbiddenState requestId="req-403-xyz" />);
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
    expect(screen.getByText("req-403-xyz")).toBeInTheDocument();
  });
});
