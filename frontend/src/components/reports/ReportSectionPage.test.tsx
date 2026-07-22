import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReportSectionPage } from "@/components/reports/ReportSectionPage";

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: {
      status: "authenticated",
      session: { role: "owner", organizationId: "org-1", userId: "user-1" },
    },
  }),
}));

vi.mock("@/components/reports/ReportsOverviewDashboard", () => ({
  ReportsOverviewDashboard: () => <h1>Reports overview</h1>,
}));

describe("ReportSectionPage route wiring", () => {
  it.each([
    [undefined, "Reports overview"],
    ["answer-quality", "Answer Quality"],
    ["source-health", "Source Health"],
    ["usage-adoption", "Usage & Adoption"],
    ["permissions-access", "Permissions & Access"],
    ["feedback-issues", "Feedback & Issues"],
    ["knowledge-gaps", "Knowledge Gaps"],
  ])("wires %s to its report dashboard", (slug, heading) => {
    render(<ReportSectionPage slug={slug} />);

    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  });
});
