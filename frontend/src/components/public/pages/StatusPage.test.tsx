import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { StatusPage } from "@/components/public/pages/StatusPage";
import type { PublicStatusSnapshot } from "@/lib/api/public-status";

vi.mock("@/components/public/PublicActionLink", () => ({
  PublicActionLink: ({
    href,
    children,
  }: {
    href: string;
    children: ReactNode;
  }) => <a href={href}>{children}</a>,
}));

const OPERATIONAL_SNAPSHOT: PublicStatusSnapshot = {
  generated_at: "2026-06-20T10:00:00.000Z",
  overall_status: "operational",
  headline: "All systems operational",
  summary: "Rudix services are operating normally.",
  uptime_notice:
    "Status updates are published for transparency and do not imply an SLA unless one is explicitly contracted.",
  components: [
    {
      key: "web_app",
      label: "Web app",
      status: "operational",
      summary: "Operational",
      affected_services: [],
      updated_at: null,
    },
    {
      key: "api",
      label: "API",
      status: "operational",
      summary: "Operational",
      affected_services: [],
      updated_at: null,
    },
  ],
  current_incidents: [],
  scheduled_maintenance: [],
  recent_history: [],
};

const DEGRADED_SNAPSHOT: PublicStatusSnapshot = {
  ...OPERATIONAL_SNAPSHOT,
  overall_status: "degraded",
  headline: "Partial service degradation",
  summary: "Some public services are slower or partially impaired.",
  components: [
    {
      ...OPERATIONAL_SNAPSHOT.components[0],
      status: "degraded",
      summary: "Some public services are slower or partially impaired.",
      affected_services: ["api"],
    },
    OPERATIONAL_SNAPSHOT.components[1],
  ],
  current_incidents: [
    {
      title: "API latency increase",
      status: "investigating",
      severity: "medium",
      kind: "incident",
      affected_services: ["api"],
      message: "We are investigating elevated latency.",
      started_at: "2026-06-20T08:00:00.000Z",
      resolved_at: null,
    },
  ],
};

const MAINTENANCE_SNAPSHOT: PublicStatusSnapshot = {
  ...OPERATIONAL_SNAPSHOT,
  overall_status: "maintenance",
  headline: "Scheduled maintenance in progress",
  summary:
    "One or more public services are undergoing planned or in-progress maintenance.",
  components: [
    {
      ...OPERATIONAL_SNAPSHOT.components[0],
      status: "maintenance",
      summary:
        "One or more public services are undergoing planned or in-progress maintenance.",
      affected_services: [],
    },
    {
      ...OPERATIONAL_SNAPSHOT.components[1],
      status: "maintenance",
      summary:
        "One or more public services are undergoing planned or in-progress maintenance.",
      affected_services: [],
    },
  ],
  scheduled_maintenance: [
    {
      title: "Scheduled maintenance",
      status: "monitoring",
      severity: "low",
      kind: "maintenance",
      affected_services: [],
      message: "Maintenance is underway.",
      started_at: "2026-06-20T09:00:00.000Z",
      resolved_at: null,
    },
  ],
  recent_history: [
    {
      title: "Search outage",
      status: "resolved",
      severity: "high",
      kind: "incident",
      affected_services: ["answering"],
      message: "Resolved.",
      started_at: "2026-06-19T09:00:00.000Z",
      resolved_at: "2026-06-19T12:00:00.000Z",
    },
  ],
};

describe("StatusPage", () => {
  it("renders an operational snapshot", () => {
    render(<StatusPage snapshot={OPERATIONAL_SNAPSHOT} loadError={null} />);

    expect(
      screen.getByRole("heading", { name: "All systems operational" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Live operational incidents" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No active incidents")).toBeInTheDocument();
    expect(screen.getByText("No scheduled maintenance")).toBeInTheDocument();
  });

  it("renders a degraded incident snapshot", () => {
    render(<StatusPage snapshot={DEGRADED_SNAPSHOT} loadError={null} />);

    expect(screen.getByText("Partial service degradation")).toBeInTheDocument();
    expect(screen.getByText("API latency increase")).toBeInTheDocument();
    expect(screen.getByText("API")).toBeInTheDocument();
  });

  it("renders a maintenance snapshot and safe fallback copy", () => {
    render(<StatusPage snapshot={MAINTENANCE_SNAPSHOT} loadError={null} />);

    expect(
      screen.getByText("Scheduled maintenance in progress"),
    ).toBeInTheDocument();
    expect(screen.getByText("Recent history")).toBeInTheDocument();
    expect(screen.getByText("Search outage")).toBeInTheDocument();
  });

  it("shows a safe fallback when data is unavailable", () => {
    render(
      <StatusPage
        snapshot={null}
        loadError="Unable to load live status data."
      />,
    );

    expect(screen.getByText("Status data unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(/Live status information is temporarily unavailable/i),
    ).toBeInTheDocument();
  });
});
