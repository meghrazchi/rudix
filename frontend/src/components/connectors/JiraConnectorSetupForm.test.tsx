import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JiraConnectorSetupForm,
  type JiraConnectorConfig,
} from "@/components/connectors/JiraConnectorSetupForm";

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderForm(overrides: Partial<Parameters<typeof JiraConnectorSetupForm>[0]> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const result = render(
    <JiraConnectorSetupForm
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { ...result, onSubmit, onCancel };
}

async function fillSiteUrl(url: string) {
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText(/Jira site URL/i));
  await user.type(screen.getByLabelText(/Jira site URL/i), url);
}

async function submitForm() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /Connect Jira|Connecting/i }));
}

// ── Rendering ─────────────────────────────────────────────────────────────────

describe("JiraConnectorSetupForm — rendering", () => {
  it("renders site URL, project keys, and JQL filter fields", () => {
    renderForm();
    expect(screen.getByLabelText(/Jira site URL/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Project keys/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/JQL filter/i)).toBeInTheDocument();
  });

  it("renders the submit button with default label", () => {
    renderForm();
    expect(screen.getByRole("button", { name: "Connect Jira" })).toBeInTheDocument();
  });

  it("renders a custom submit label", () => {
    renderForm({ submitLabel: "Save settings" });
    expect(screen.getByRole("button", { name: "Save settings" })).toBeInTheDocument();
  });

  it("renders Cancel button when onCancel is provided", () => {
    renderForm();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("does not render Cancel button when onCancel is omitted", () => {
    renderForm({ onCancel: undefined });
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("pre-populates fields from initialConfig", () => {
    renderForm({
      initialConfig: {
        site_url: "https://acme.atlassian.net",
        project_keys: ["PROJ", "WEB"],
        jql_filter: "status = Open",
      },
    });
    expect(screen.getByLabelText(/Jira site URL/i)).toHaveValue("https://acme.atlassian.net");
    expect(screen.getByLabelText(/Project keys/i)).toHaveValue("PROJ, WEB");
    expect(screen.getByLabelText(/JQL filter/i)).toHaveValue("status = Open");
  });

  it("shows loading label and disables button when isSubmitting", () => {
    renderForm({ isSubmitting: true });
    const btn = screen.getByRole("button", { name: "Connecting…" });
    expect(btn).toBeDisabled();
  });
});

// ── Validation ────────────────────────────────────────────────────────────────

describe("JiraConnectorSetupForm — validation", () => {
  it("shows error when site URL is empty on submit", async () => {
    renderForm();
    await submitForm();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/required/i);
  });

  it("shows error when site URL lacks http scheme", async () => {
    renderForm();
    await fillSiteUrl("mysite.atlassian.net");
    await submitForm();
    expect(await screen.findByRole("alert")).toHaveTextContent(/https?/i);
  });

  it("does not show error for valid https URL", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://mysite.atlassian.net");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows inline error on blur for invalid URL", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText(/Jira site URL/i), "not-a-url");
    await user.tab();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("does not call onSubmit when validation fails", async () => {
    const { onSubmit } = renderForm();
    await submitForm();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

// ── Submission ────────────────────────────────────────────────────────────────

describe("JiraConnectorSetupForm — submission", () => {
  it("calls onSubmit with trimmed site URL", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("  https://mysite.atlassian.net  ");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as JiraConnectorConfig;
    expect(config.site_url).toBe("https://mysite.atlassian.net");
  });

  it("calls onSubmit with parsed project_keys array", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await user.type(screen.getByLabelText(/Project keys/i), "PROJ, web, TEAM");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as JiraConnectorConfig;
    expect(config.project_keys).toEqual(["PROJ", "WEB", "TEAM"]);
  });

  it("calls onSubmit with empty project_keys when blank", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as JiraConnectorConfig;
    expect(config.project_keys).toEqual([]);
  });

  it("calls onSubmit with trimmed jql_filter", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await user.type(screen.getByLabelText(/JQL filter/i), "  status != Done  ");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as JiraConnectorConfig;
    expect(config.jql_filter).toBe("status != Done");
  });

  it("calls onSubmit with empty jql_filter when blank", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as JiraConnectorConfig;
    expect(config.jql_filter).toBe("");
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────────

describe("JiraConnectorSetupForm — cancel", () => {
  it("calls onCancel when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderForm();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("Cancel button is disabled while submitting", () => {
    renderForm({ isSubmitting: true });
    const cancelBtn = screen.getByRole("button", { name: "Cancel" });
    expect(cancelBtn).toBeDisabled();
  });
});
