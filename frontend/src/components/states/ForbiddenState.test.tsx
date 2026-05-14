import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ForbiddenState } from "@/components/states/ForbiddenState";

describe("ForbiddenState", () => {
  it("renders default forbidden state actions", () => {
    render(<ForbiddenState />);

    expect(screen.getByRole("heading", { name: "Forbidden" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to dashboard" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });

  it("renders safe trace/request id when provided", () => {
    render(<ForbiddenState requestId="req-403-abc" />);

    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
    expect(screen.getByText("req-403-abc")).toBeInTheDocument();
  });

  it("hides invalid trace/request id values", () => {
    render(<ForbiddenState requestId="invalid request id" />);

    expect(screen.queryByText("Trace ID:")).not.toBeInTheDocument();
  });

  it("uses custom title and description for inline states", () => {
    render(
      <ForbiddenState
        compact
        title="Action blocked"
        description="You are not allowed to run this operation for the selected organization."
      />,
    );

    expect(screen.getByRole("heading", { name: "Action blocked" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "You are not allowed to run this operation for the selected organization.",
      ),
    ).toBeInTheDocument();
  });

  it("renders configured support action", () => {
    const originalEnv = { ...process.env };
    try {
      process.env = { ...originalEnv, NEXT_PUBLIC_SUPPORT_URL: "https://support.rudix.local" };

      render(<ForbiddenState />);

      expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute(
        "href",
        "https://support.rudix.local",
      );
    } finally {
      process.env = originalEnv;
    }
  });
});
