import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  GoogleDriveConnectorSetupForm,
  type GoogleDriveConnectorConfig,
} from "@/components/connectors/GoogleDriveConnectorSetupForm";

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderForm(
  overrides: Partial<Parameters<typeof GoogleDriveConnectorSetupForm>[0]> = {},
) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const result = render(
    <GoogleDriveConnectorSetupForm
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { ...result, onSubmit, onCancel };
}

async function submitForm() {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", {
      name: /Connect Google Drive|Connecting/i,
    }),
  );
}

// ── Rendering ─────────────────────────────────────────────────────────────────

describe("GoogleDriveConnectorSetupForm — rendering", () => {
  it("renders folder IDs and include-shared-drives fields", () => {
    renderForm();
    expect(screen.getByLabelText(/Folder IDs/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Include Shared Drives/i)).toBeInTheDocument();
  });

  it("does not render shared drive IDs field by default", () => {
    renderForm();
    expect(
      screen.queryByLabelText(/Shared Drive IDs/i),
    ).not.toBeInTheDocument();
  });

  it("renders shared drive IDs field when include-shared-drives is checked", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByLabelText(/Include Shared Drives/i));
    expect(screen.getByLabelText(/Shared Drive IDs/i)).toBeInTheDocument();
  });

  it("renders the submit button with default label", () => {
    renderForm();
    expect(
      screen.getByRole("button", { name: "Connect Google Drive" }),
    ).toBeInTheDocument();
  });

  it("renders a custom submit label", () => {
    renderForm({ submitLabel: "Save config" });
    expect(
      screen.getByRole("button", { name: "Save config" }),
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

  it("pre-populates folder_ids from initialConfig", () => {
    renderForm({
      initialConfig: {
        folder_ids: ["folder_abc", "folder_xyz"],
        include_shared_drives: false,
        drive_ids: [],
      },
    });
    expect(screen.getByLabelText(/Folder IDs/i)).toHaveValue(
      "folder_abc, folder_xyz",
    );
  });

  it("pre-populates include_shared_drives checkbox from initialConfig", () => {
    renderForm({
      initialConfig: {
        folder_ids: [],
        include_shared_drives: true,
        drive_ids: ["drive_001"],
      },
    });
    expect(screen.getByLabelText(/Include Shared Drives/i)).toBeChecked();
  });

  it("pre-populates drive_ids when include_shared_drives is true in initialConfig", () => {
    renderForm({
      initialConfig: {
        folder_ids: [],
        include_shared_drives: true,
        drive_ids: ["drive_001", "drive_002"],
      },
    });
    expect(screen.getByLabelText(/Shared Drive IDs/i)).toHaveValue(
      "drive_001, drive_002",
    );
  });

  it("include_shared_drives checkbox is unchecked by default", () => {
    renderForm();
    expect(screen.getByLabelText(/Include Shared Drives/i)).not.toBeChecked();
  });

  it("shows loading label and disables button when isSubmitting", () => {
    renderForm({ isSubmitting: true });
    const btn = screen.getByRole("button", { name: "Connecting…" });
    expect(btn).toBeDisabled();
  });
});

// ── Validation ────────────────────────────────────────────────────────────────

describe("GoogleDriveConnectorSetupForm — validation", () => {
  it("does not show error when folder IDs field is blank (optional)", async () => {
    const { onSubmit } = renderForm();
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows error when a folder ID contains a slash", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText(/Folder IDs/i), "some/invalid/path");
    await submitForm();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/slash/i);
  });

  it("shows error when a folder ID contains a space", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText(/Folder IDs/i), "has space");
    await submitForm();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("does not call onSubmit when folder ID validation fails", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await user.type(screen.getByLabelText(/Folder IDs/i), "bad/id");
    await submitForm();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows inline error on blur for invalid folder ID", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText(/Folder IDs/i), "bad/folder");
    await user.tab();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("shows drive_ids error when shared drive ID contains a slash", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByLabelText(/Include Shared Drives/i));
    await user.type(screen.getByLabelText(/Shared Drive IDs/i), "bad/drive");
    await submitForm();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/slash/i);
  });
});

// ── Submission ────────────────────────────────────────────────────────────────

describe("GoogleDriveConnectorSetupForm — submission", () => {
  it("calls onSubmit with empty arrays when form is blank", async () => {
    const { onSubmit } = renderForm();
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as GoogleDriveConnectorConfig;
    expect(config.folder_ids).toEqual([]);
    expect(config.drive_ids).toEqual([]);
    expect(config.include_shared_drives).toBe(false);
  });

  it("calls onSubmit with parsed and trimmed folder_ids", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await user.type(
      screen.getByLabelText(/Folder IDs/i),
      "  folder_abc  ,  folder_xyz  ",
    );
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as GoogleDriveConnectorConfig;
    expect(config.folder_ids).toEqual(["folder_abc", "folder_xyz"]);
  });

  it("calls onSubmit with include_shared_drives true when checkbox is checked", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await user.click(screen.getByLabelText(/Include Shared Drives/i));
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as GoogleDriveConnectorConfig;
    expect(config.include_shared_drives).toBe(true);
  });

  it("calls onSubmit with parsed drive_ids when include_shared_drives is true", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await user.click(screen.getByLabelText(/Include Shared Drives/i));
    await user.type(
      screen.getByLabelText(/Shared Drive IDs/i),
      "drive_001, drive_002",
    );
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as GoogleDriveConnectorConfig;
    expect(config.drive_ids).toEqual(["drive_001", "drive_002"]);
  });

  it("calls onSubmit with empty drive_ids when include_shared_drives is false", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm();
    await user.type(screen.getByLabelText(/Folder IDs/i), "folder_abc");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const config = onSubmit.mock.calls[0][0] as GoogleDriveConnectorConfig;
    expect(config.drive_ids).toEqual([]);
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────────

describe("GoogleDriveConnectorSetupForm — cancel", () => {
  it("calls onCancel when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderForm();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("Cancel button is disabled while submitting", () => {
    renderForm({ isSubmitting: true });
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});
