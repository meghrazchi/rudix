import { QueryClient } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DynamicRuleBuilder,
  emptyRuleSet,
} from "@/components/collections/DynamicRuleBuilder";
import type { DynamicRuleSet } from "@/lib/api/collections";
import { createTestQueryClient, renderWithProviders } from "@/test/render";

// ── Mock: collections API (preview) ────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  previewCollectionRules: vi.fn(),
}));

vi.mock("@/lib/api/collections", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/collections")>();
  return {
    ...actual,
    previewCollectionRules: (...args: unknown[]) =>
      mockApi.previewCollectionRules(...args),
  };
});

// ── Setup ─────────────────────────────────────────────────────────────────

let queryClient: QueryClient;

beforeEach(() => {
  queryClient = createTestQueryClient();
  vi.clearAllMocks();
});

// ── emptyRuleSet ────────────────────────────────────────────────────────────

describe("emptyRuleSet", () => {
  it("returns a valid rule set with one condition", () => {
    const rs = emptyRuleSet();
    expect(rs.logic).toBe("and");
    expect(rs.conditions).toHaveLength(1);
  });
});

// ── DynamicRuleBuilder rendering ────────────────────────────────────────────

describe("DynamicRuleBuilder", () => {
  function makeRuleSet(overrides?: Partial<DynamicRuleSet>): DynamicRuleSet {
    return {
      logic: "and",
      conditions: [{ field: "file_type", operator: "eq", value: "pdf" }],
      ...overrides,
    };
  }

  it("renders logic toggle buttons", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    expect(screen.getByText("All conditions")).toBeInTheDocument();
    expect(screen.getByText("Any condition")).toBeInTheDocument();
  });

  it("renders a condition row with field/operator selectors", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    expect(screen.getByLabelText("Rule field")).toBeInTheDocument();
    expect(screen.getByLabelText("Rule operator")).toBeInTheDocument();
  });

  it("calls onChange when logic is switched to OR", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet({ logic: "and" })}
        onChange={onChange}
      />,
      { queryClient },
    );

    await user.click(screen.getByText("Any condition"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ logic: "or" }),
    );
  });

  it("calls onChange when field is changed", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    await user.selectOptions(screen.getByLabelText("Rule field"), "language");
    expect(onChange).toHaveBeenCalled();
    const called = onChange.mock.calls[0][0] as DynamicRuleSet;
    expect(called.conditions[0].field).toBe("language");
  });

  it("shows add condition button and calls onChange", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    await user.click(screen.getByText("Add condition"));
    expect(onChange).toHaveBeenCalled();
    const called = onChange.mock.calls[0][0] as DynamicRuleSet;
    expect(called.conditions).toHaveLength(2);
  });

  it("shows remove button when more than one condition", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet({
          conditions: [
            { field: "file_type", operator: "eq", value: "pdf" },
            { field: "language", operator: "eq", value: "en" },
          ],
        })}
        onChange={onChange}
      />,
      { queryClient },
    );

    const removeButtons = screen.getAllByLabelText("Remove condition");
    expect(removeButtons).toHaveLength(2);
  });

  it("does not show remove button for the only condition", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    expect(screen.queryByLabelText("Remove condition")).not.toBeInTheDocument();
  });

  it("shows multi-value checkboxes for 'in' operator", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet({
          conditions: [
            { field: "file_type", operator: "in", value: ["pdf", "docx"] },
          ],
        })}
        onChange={onChange}
      />,
      { queryClient },
    );

    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("DOCX")).toBeInTheDocument();
  });

  it("shows preview toggle when collectionId is provided", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    expect(screen.getByText("Show document preview")).toBeInTheDocument();
  });

  it("does not show preview toggle when collectionId is null", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId={null}
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    expect(screen.queryByText("Show document preview")).not.toBeInTheDocument();
  });

  it("shows preview panel after clicking 'Show document preview'", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    await user.click(screen.getByText("Show document preview"));
    expect(screen.getByText("Run preview")).toBeInTheDocument();
  });

  it("calls previewCollectionRules and shows result", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    mockApi.previewCollectionRules.mockResolvedValue({
      total: 2,
      items: [
        {
          document_id: "doc-1",
          filename: "report.pdf",
          file_type: "pdf",
          language: "en",
          status: "indexed",
          trust_status: "current",
          tags: null,
          ingestion_source: "upload",
        },
      ],
    });

    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    await user.click(screen.getByText("Show document preview"));
    await user.click(screen.getByText("Run preview"));

    await waitFor(() => {
      expect(screen.getByText("2 documents match")).toBeInTheDocument();
    });
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
  });

  it("shows error when preview fails", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    mockApi.previewCollectionRules.mockRejectedValue(new Error("Server error"));

    renderWithProviders(
      <DynamicRuleBuilder
        collectionId="col-1"
        value={makeRuleSet()}
        onChange={onChange}
      />,
      { queryClient },
    );

    await user.click(screen.getByText("Show document preview"));
    await user.click(screen.getByText("Run preview"));

    await waitFor(() => {
      expect(screen.getByText(/Server error/)).toBeInTheDocument();
    });
  });
});
