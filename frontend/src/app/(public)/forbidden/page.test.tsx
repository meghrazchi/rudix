import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ForbiddenPage from "./page";

describe("ForbiddenPage", () => {
  it("renders a safe forbidden view without leaking requested route details", async () => {
    const page = await ForbiddenPage({
      searchParams: Promise.resolve({
        from: "/admin/documents/private-record-123",
      }),
    });

    render(page);

    expect(
      screen.getByRole("heading", { name: "Forbidden" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Requested route/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText("/admin/documents/private-record-123"),
    ).not.toBeInTheDocument();
  });

  it("displays safe trace/request ID when provided", async () => {
    const page = await ForbiddenPage({
      searchParams: Promise.resolve({
        rid: "req-403-abc",
      }),
    });

    render(page);

    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
    expect(screen.getByText("req-403-abc")).toBeInTheDocument();
  });

  it("hides invalid trace/request IDs", async () => {
    const page = await ForbiddenPage({
      searchParams: Promise.resolve({
        rid: "bad request id",
      }),
    });

    render(page);

    expect(screen.queryByText("Trace ID:")).not.toBeInTheDocument();
  });
});
