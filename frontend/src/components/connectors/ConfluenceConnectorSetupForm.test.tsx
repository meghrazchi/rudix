import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ConfluenceConnectorSetupForm,
  type ConfluenceConnectorConfig,
} from "@/components/connectors/ConfluenceConnectorSetupForm";

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderForm(
  overrides: Partial<Parameters<typeof ConfluenceConnectorSetupForm>[0]> = {},
) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const result = render(
    <ConfluenceConnectorSetupForm
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { ...result, onSubmit, onCancel };
}

async function fillSiteUrl(url: string) {
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText(/Confluence site URL/i));
  await user.type(screen.getByLabelText(/Confluence site URL/i), url);
}

async function submitForm() {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: /Connect Confluence|Connecting/i }),
  );
}

// ── Rendering ─────────────────────────────────────────────────────────────────

describe("ConfluenceConnectorSetupForm — rendering", () => {
  it("renders site URL, space keys, CQL filter, and include-comments fields", () => {
    renderForm();
    expect(screen.getByLabelText(/Confluence site URL/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Space keys/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/CQL filter/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Include page comments/i)).toBeInTheDocument();
  });

  it("renders the submit button with default label", () => {
    renderForm();
    expect(
      screen.getByRole("button", { name: "Connect Confluence" }),
    ).toBeInTheDocument();
  });

  it("renders a custom submit label", () => {
    renderForm({ submitLabel: "Save settings" });
    expect(
      screen.getByRole("button", { name: "Save settings" }),
    ).toBeInTheDocument();
  });

  it("renders Cancel button when onCancel is provided", () => {
    renderForm();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("does not render Cancel button when onCancel is omitted", () => {
    renderForm({ onCancel: undefined });
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
  });

  it("pre-populates fields from initialConfig", () => {
    renderForm({
      initialConfig: {
        site_url: "https://acme.atlassian.net",
        space_keys: ["DOCS", "ENG"],
        cql_filter: 'label = "docs"',
        include_comments: true,
      },
    });
    expect(screen.getByLabelText(/Confluence site URL/i)).toHaveValue(
      "https://acme.atlassian.net",
    );
    expect(screen.getByLabelText(/Space keys/i)).toHaveValue("DOCS, ENG");
    expect(screen.getByLabelText(/CQL filter/i)).toHaveValue('label = "docs"');
    expect(screen.getByLabelText(/Include page comments/i)).toBeChecked();
  });

  it("include_comments checkbox is unchecked by default", () => {
    renderForm();
    expect(screen.getByLabelText(/Include page comments/i)).not.toBeChecked();
  });

  it("shows loading label and disables button when isSubmitting", () => {
    renderForm({ isSubmitting: true });
    const btn = screen.getByRole("button", { name: "Connecting…" });
    expect(btn).toBeDisabled();
  });
});

// ── Validation ────────────────────────────────────────────────────────────────

describe("ConfluenceConnectorSetupForm — validation", () => {
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
    await user.type(screen.getByLabelText(/Confluence site URL/i), "not-a-url");
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

describe("ConfluenceConnectorSetupForm — submission", () => {
  it("calls onSubmit with trimmed site URL", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("  https://mysite.atlassian.net  ");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as ConfluenceConnectorConfig;
    expect(config.site_url).toBe("https://mysite.atlassian.net");
  });

  it("calls onSubmit with parsed space_keys array uppercased", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await user.type(screen.getByLabelText(/Space keys/i), "docs, eng, team");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as ConfluenceConnectorConfig;
    expect(config.space_keys).toEqual(["DOCS", "ENG", "TEAM"]);
  });

  it("calls onSubmit with empty space_keys when blank", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as ConfluenceConnectorConfig;
    expect(config.space_keys).toEqual([]);
  });

  it("calls onSubmit with trimmed cql_filter", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await user.type(screen.getByLabelText(/CQL filter/i), '  label = "docs"  ');
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as ConfluenceConnectorConfig;
    expect(config.cql_filter).toBe('label = "docs"');
  });

  it("calls onSubmit with include_comments true when checkbox is checked", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await user.click(screen.getByLabelText(/Include page comments/i));
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as ConfluenceConnectorConfig;
    expect(config.include_comments).toBe(true);
  });

  it("calls onSubmit with include_comments false by default", async () => {
    const { onSubmit } = renderForm();
    await fillSiteUrl("https://acme.atlassian.net");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as ConfluenceConnectorConfig;
    expect(config.include_comments).toBe(false);
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────────

describe("ConfluenceConnectorSetupForm — cancel", () => {
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
