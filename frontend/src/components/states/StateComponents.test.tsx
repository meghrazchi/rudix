import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { normalizeApiError } from "@/lib/api/errors";

describe("State components", () => {
  it("renders loading state", () => {
    render(<LoadingState title="Loading documents..." description="Please wait." />);
    expect(screen.getByText("Loading documents...")).toBeInTheDocument();
    expect(screen.getByText("Please wait.")).toBeInTheDocument();
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

  it("renders direct rate limit state", () => {
    render(<RateLimitState requestId="trace-rate-limit" />);
    expect(screen.getByText("Rate limit reached")).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
  });
});
