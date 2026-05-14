import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ForbiddenAliasPage from "@/app/403/page";

describe("ForbiddenAliasPage", () => {
  it("renders the forbidden page alias with safe request id support", async () => {
    const page = await ForbiddenAliasPage({
      searchParams: Promise.resolve({
        rid: "req-403-alias",
      }),
    });

    render(page);

    expect(screen.getByRole("heading", { name: "Forbidden" })).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
    expect(screen.getByText("req-403-alias")).toBeInTheDocument();
  });
});
