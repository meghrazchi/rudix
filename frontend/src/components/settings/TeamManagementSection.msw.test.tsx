import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { TeamManagementSection } from "@/components/settings/TeamManagementSection";
import { clearSessionStorage, writeSessionToStorage } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";
const membersEndpoint = "/team/members";
const invitesEndpoint = "/team/members/invite";

let observedAuthHeader: string | null = null;
let observedOrgHeader: string | null = null;
let observedMembersLimit: string | null = null;
let observedMembersOffset: string | null = null;
let inviteCount = 0;
let lastInvitePayload: Record<string, unknown> | null = null;

const server = setupServer(
  http.get(`${apiBaseUrl}${membersEndpoint}`, ({ request }) => {
    observedAuthHeader = request.headers.get("authorization");
    observedOrgHeader = request.headers.get("x-organization-id");
    observedMembersLimit = new URL(request.url).searchParams.get("limit");
    observedMembersOffset = new URL(request.url).searchParams.get("offset");
    return HttpResponse.json({
      items: [
        {
          member_id: "member-1",
          user_id: "user-1",
          name: "Admin User",
          email: "admin@example.com",
          role: "admin",
          status: "active",
          created_at: "2026-05-16T10:00:00Z",
          updated_at: "2026-05-16T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
  }),
  http.post(`${apiBaseUrl}${invitesEndpoint}`, async ({ request }) => {
    inviteCount += 1;
    lastInvitePayload = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      member: {
        member_id: "member-2",
        user_id: null,
        name: "teammate@example.com",
        email: "teammate@example.com",
        role: "viewer",
        status: "invited",
        created_at: "2026-05-16T10:30:00Z",
        updated_at: "2026-05-16T10:30:00Z",
      },
      invited: true,
    });
  }),
);

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TeamManagementSection role="admin" />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  clearSessionStorage();
  observedAuthHeader = null;
  observedOrgHeader = null;
  observedMembersLimit = null;
  observedMembersOffset = null;
  inviteCount = 0;
  lastInvitePayload = null;
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  process.env.NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL = membersEndpoint;
  process.env.NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL = invitesEndpoint;
  process.env.NEXT_PUBLIC_TEAM_MEMBER_ROLE_UPDATE_URL_TEMPLATE = "";
  process.env.NEXT_PUBLIC_TEAM_MEMBER_REMOVE_URL_TEMPLATE = "";

  writeSessionToStorage({
    userId: "user-1",
    email: "admin@example.com",
    role: "admin",
    organizationId: "c8ae2f17-c58e-499e-88bf-e6b0a8648c21",
    organizationName: "Org One",
    accessToken: "session-access-token",
  });
});

describe("TeamManagementSection MSW", () => {
  it("loads organization members with shared API client auth headers", async () => {
    renderSection();

    expect(await screen.findByText("Admin User")).toBeInTheDocument();
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    expect(observedAuthHeader).toBe("Bearer session-access-token");
    expect(observedOrgHeader).toBe("c8ae2f17-c58e-499e-88bf-e6b0a8648c21");
    expect(observedMembersLimit).toBe("10");
    expect(observedMembersOffset).toBe("0");
  });

  it("submits invite mutation when membership invite endpoint is available", async () => {
    renderSection();
    await screen.findByText("Admin User");

    await userEvent.type(screen.getByPlaceholderText("teammate@company.com"), "teammate@example.com");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Role" }), "viewer");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));

    await waitFor(() => {
      expect(inviteCount).toBe(1);
    });
    expect(lastInvitePayload).toMatchObject({
      email: "teammate@example.com",
      role: "viewer",
    });
    expect(await screen.findByText("Invite sent successfully.")).toBeInTheDocument();
  });
});
