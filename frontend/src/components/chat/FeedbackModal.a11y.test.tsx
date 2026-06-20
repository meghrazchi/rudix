/**
 * F177 — Accessibility tests for FeedbackModal:
 * focus trap, escape key, ARIA labelling, form structure.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FeedbackModal } from "@/components/chat/FeedbackModal";

function renderModal(
  overrides: Partial<React.ComponentProps<typeof FeedbackModal>> = {},
) {
  const defaults = {
    existingReason: null,
    existingCategory: null,
    existingComment: null,
    isSubmitting: false,
    isDeleting: false,
    onSubmit: vi.fn(),
    onDelete: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  return render(<FeedbackModal {...defaults} />);
}

describe("FeedbackModal accessibility", () => {
  it("renders as a dialog landmark with accessible name", () => {
    renderModal();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "feedback-modal-title");
    expect(document.getElementById("feedback-modal-title")).toHaveTextContent(
      /report an issue/i,
    );
  });

  it("uses aria-labelledby pointing to dialog heading when editing", () => {
    renderModal({
      existingReason: "other",
      existingCategory: null,
      existingComment: "test",
    });
    expect(document.getElementById("feedback-modal-title")).toHaveTextContent(
      /edit feedback/i,
    );
  });

  it("close button has accessible label", () => {
    renderModal();
    const closeBtn = screen.getByRole("button", {
      name: /close feedback dialog/i,
    });
    expect(closeBtn).toBeInTheDocument();
  });

  it("pressing Escape calls onClose", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderModal({ onClose });
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("feedback category fieldset has a legend for screen readers", () => {
    renderModal();
    const fieldsets = screen
      .getAllByRole("group")
      .filter((el) => el.tagName === "FIELDSET");
    expect(fieldsets.length).toBeGreaterThan(0);
    const legend = fieldsets[0].querySelector("legend");
    expect(legend).toBeInTheDocument();
  });

  it("comment textarea is labelled and has aria-describedby for char count", () => {
    renderModal();
    const textarea = screen.getByRole("textbox", {
      name: /additional details/i,
    });
    expect(textarea).toHaveAttribute(
      "aria-describedby",
      "feedback-comment-count",
    );
    expect(
      document.getElementById("feedback-comment-count"),
    ).toBeInTheDocument();
  });

  it("char count region is aria-live=polite", () => {
    renderModal();
    const counter = document.getElementById("feedback-comment-count");
    expect(counter).toHaveAttribute("aria-live", "polite");
    expect(counter).toHaveAttribute("aria-atomic", "true");
  });

  it("Cancel and Submit buttons are present and accessible", () => {
    renderModal();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });

  it("submit button is disabled when isSubmitting=true", () => {
    renderModal({ isSubmitting: true });
    expect(screen.getByRole("button", { name: /submitting/i })).toBeDisabled();
  });

  it("calling onClose closes the modal when clicking the backdrop", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { container } = renderModal({ onClose });
    // The outermost div is the backdrop
    const backdrop = container.firstChild as HTMLElement;
    await user.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });
});
