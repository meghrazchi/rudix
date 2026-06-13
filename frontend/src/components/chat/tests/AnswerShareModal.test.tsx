import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnswerShareModal } from "@/components/chat/AnswerShareModal";
import { renderWithProviders } from "@/test/render";

const apiBaseUrl = "http://api.test";
const MESSAGE_ID = "msg-123";
const SHARE_ID = "share-abc";
const TOKEN = "tok-xyz";

const mockShare = {
  share_id: SHARE_ID,
  message_id: MESSAGE_ID,
  token: TOKEN,
  access_mode: "org_only",
  allowed_user_ids: [],
  has_password: false,
  created_at: "2026-06-15T10:00:00Z",
  expires_at: null,
  is_revoked: false,
  shared_by_user_id: "user-1",
};

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
});

function render(onClose = vi.fn()) {
  return renderWithProviders(
    <AnswerShareModal messageId={MESSAGE_ID} onClose={onClose} />,
  );
}

// ─── server ──────────────────────────────────────────────────────────────────

const server = setupServer(
  http.get(`${apiBaseUrl}/chat/messages/:id/shares`, () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.post(`${apiBaseUrl}/chat/messages/:id/shares`, () =>
    HttpResponse.json(mockShare, { status: 201 }),
  ),
  http.delete(
    `${apiBaseUrl}/chat/messages/:id/shares/:shareId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ─── tests ───────────────────────────────────────────────────────────────────

describe("AnswerShareModal", () => {
  it("renders modal title and security notice", async () => {
    render();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Share answer")).toBeInTheDocument();
    expect(
      screen.getByText(/Viewers must be signed-in members/),
    ).toBeInTheDocument();
  });

  it("shows empty state when no shares exist", async () => {
    render();
    expect(
      await screen.findByText("No active share links for this answer."),
    ).toBeInTheDocument();
  });

  it("shows active share after creating one", async () => {
    server.use(
      http.get(`${apiBaseUrl}/chat/messages/:id/shares`, () =>
        HttpResponse.json({ items: [mockShare], total: 1 }),
      ),
    );
    render();
    await waitFor(() => {
      expect(screen.getByText(/tok-xyz/)).toBeInTheDocument();
    });
  });

  it("calls onClose when Escape is pressed", async () => {
    const onClose = vi.fn();
    render(onClose);
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when close button is clicked", async () => {
    const onClose = vi.fn();
    render(onClose);
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("generates a share link when Generate link is clicked", async () => {
    let created = false;
    server.use(
      http.post(`${apiBaseUrl}/chat/messages/:id/shares`, () => {
        created = true;
        return HttpResponse.json(mockShare, { status: 201 });
      }),
    );
    render();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Generate link" }));
    await waitFor(() => expect(created).toBe(true));
  });

  it("shows specific_users textarea when Specific users access mode is selected", async () => {
    render();
    await screen.findByRole("dialog");
    await userEvent.click(
      screen.getByRole("button", { name: "Specific users" }),
    );
    expect(
      screen.getByPlaceholderText(/uuid-1, uuid-2/),
    ).toBeInTheDocument();
  });

  it("disables Generate link when specific_users mode has empty user list", async () => {
    render();
    await screen.findByRole("dialog");
    await userEvent.click(
      screen.getByRole("button", { name: "Specific users" }),
    );
    const btn = screen.getByRole("button", { name: "Generate link" });
    expect(btn).toBeDisabled();
  });

  it("shows password field when Require password is checked", async () => {
    render();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("checkbox"));
    expect(
      screen.getByPlaceholderText(/Enter link password/),
    ).toBeInTheDocument();
  });

  it("disables Generate link when password enabled but too short", async () => {
    render();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("checkbox"));
    const passwordInput = screen.getByPlaceholderText(/Enter link password/);
    await userEvent.type(passwordInput, "ab");
    expect(
      screen.getByRole("button", { name: "Generate link" }),
    ).toBeDisabled();
  });
});
