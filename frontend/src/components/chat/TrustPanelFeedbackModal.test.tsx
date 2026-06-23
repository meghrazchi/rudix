import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  TrustPanelFeedbackModal,
  type TrustPanelCitationRef,
} from "@/components/chat/TrustPanelFeedbackModal";

const onSubmit = vi.fn();
const onClose = vi.fn();

function renderModal(
  overrides: {
    activeWarnings?: string[];
    citations?: TrustPanelCitationRef[];
    traceId?: string | null;
    trustScore?: number | null;
    trustLevel?: string | null;
    isSubmitting?: boolean;
  } = {},
) {
  return render(
    <TrustPanelFeedbackModal
      activeWarnings={overrides.activeWarnings ?? []}
      citations={overrides.citations ?? []}
      traceId={overrides.traceId ?? null}
      trustScore={overrides.trustScore ?? 0.65}
      trustLevel={overrides.trustLevel ?? "medium"}
      isSubmitting={overrides.isSubmitting ?? false}
      onSubmit={onSubmit}
      onClose={onClose}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TrustPanelFeedbackModal", () => {
  it("renders the dialog with correct title", () => {
    renderModal();
    expect(
      screen.getByRole("dialog", { name: /report answer issue/i }),
    ).toBeInTheDocument();
  });

  it("shows all 7 trust-panel categories", () => {
    renderModal();
    expect(screen.getByLabelText(/wrong answer/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/bad citation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/missing citation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/stale source/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/conflicting source/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/not enough detail/i)).toBeInTheDocument();
    expect(
      screen.getByLabelText(/should have said not found/i),
    ).toBeInTheDocument();
  });

  it("pre-selects stale_source when freshness warning is active", () => {
    renderModal({
      activeWarnings: ["One or more cited sources are stale or expired."],
    });
    const staleRadio = screen.getByDisplayValue("stale_source");
    expect(staleRadio).toBeChecked();
  });

  it("pre-selects conflicting_source when conflict warning is active", () => {
    renderModal({
      activeWarnings: ["Sources disagree on one or more claims."],
    });
    const conflictRadio = screen.getByDisplayValue("conflicting_source");
    expect(conflictRadio).toBeChecked();
  });

  it("pre-selects wrong_answer when verification failed warning is active", () => {
    renderModal({
      activeWarnings: [
        "Answer verification failed — claims may not be fully grounded.",
      ],
    });
    const wrongRadio = screen.getByDisplayValue("wrong_answer");
    expect(wrongRadio).toBeChecked();
  });

  it("calls onClose when the close button is clicked", async () => {
    renderModal();
    await userEvent.click(
      screen.getByRole("button", { name: /close report dialog/i }),
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when Cancel is clicked", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("submits with null category when 'Other / not listed' is selected", async () => {
    renderModal();
    await userEvent.click(screen.getByDisplayValue(""));
    await userEvent.click(
      screen.getByRole("button", { name: /report issue/i }),
    );
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ category: null }),
    );
  });

  it("submits selected category and comment", async () => {
    renderModal();
    await userEvent.click(screen.getByDisplayValue("bad_citation"));
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "Citation points to wrong section.");
    await userEvent.click(
      screen.getByRole("button", { name: /report issue/i }),
    );
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "bad_citation",
        comment: "Citation points to wrong section.",
      }),
    );
  });

  it("passes traceId and trust metadata in submit payload", async () => {
    renderModal({
      traceId: "trace-abc123",
      trustScore: 0.35,
      trustLevel: "low",
    });
    await userEvent.click(
      screen.getByRole("button", { name: /report issue/i }),
    );
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        traceId: "trace-abc123",
        trustScore: 0.35,
        trustLevel: "low",
      }),
    );
  });

  it("shows trace ID badge when traceId is provided", () => {
    renderModal({ traceId: "trace-xyz987" });
    expect(screen.getByText("trace-xyz987")).toBeInTheDocument();
  });

  it("does not show trace ID section when traceId is null", () => {
    renderModal({ traceId: null });
    expect(screen.queryByText(/trace id/i)).not.toBeInTheDocument();
  });

  it("renders citation checkboxes when citations are provided", () => {
    const citations: TrustPanelCitationRef[] = [
      { document_id: "doc-1", chunk_id: "chunk-1", title: "Policy Guide v2" },
      { document_id: "doc-2", chunk_id: "chunk-2", title: "HR Handbook 2026" },
    ];
    renderModal({ citations });
    expect(screen.getByLabelText("Policy Guide v2")).toBeInTheDocument();
    expect(screen.getByLabelText("HR Handbook 2026")).toBeInTheDocument();
  });

  it("does not render citation section when no citations", () => {
    renderModal({ citations: [] });
    expect(
      screen.queryByText(/flag specific sources/i),
    ).not.toBeInTheDocument();
  });

  it("submits selected citation IDs in payload", async () => {
    const citations: TrustPanelCitationRef[] = [
      { document_id: "doc-1", chunk_id: "chunk-1", title: "Source A" },
      { document_id: "doc-2", chunk_id: "chunk-2", title: "Source B" },
    ];
    renderModal({ citations });
    await userEvent.click(screen.getByLabelText("Source A"));
    await userEvent.click(
      screen.getByRole("button", { name: /report issue/i }),
    );
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ selectedCitationIds: ["doc-1"] }),
    );
  });

  it("toggling a citation on then off removes it from selectedCitationIds", async () => {
    const citations: TrustPanelCitationRef[] = [
      { document_id: "doc-1", chunk_id: "chunk-1", title: "Source A" },
    ];
    renderModal({ citations });
    const checkbox = screen.getByLabelText("Source A");
    await userEvent.click(checkbox); // check
    await userEvent.click(checkbox); // uncheck
    await userEvent.click(
      screen.getByRole("button", { name: /report issue/i }),
    );
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ selectedCitationIds: [] }),
    );
  });

  it("disables submit button while isSubmitting is true", () => {
    renderModal({ isSubmitting: true });
    const submitBtn = screen.getByRole("button", { name: /reporting/i });
    expect(submitBtn).toBeDisabled();
  });

  it("shows 'Reporting...' text while submitting", () => {
    renderModal({ isSubmitting: true });
    expect(screen.getByText("Reporting…")).toBeInTheDocument();
  });

  it("updates character count as comment is typed", async () => {
    renderModal();
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "abc");
    expect(screen.getByText("3/1000")).toBeInTheDocument();
  });
});
