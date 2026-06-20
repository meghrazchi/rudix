import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  ConflictSourceComparison,
  ConflictWarningCard,
} from "@/components/chat/ConflictIndicators";
import type { ChatCitationResponse } from "@/lib/api/chat";

describe("ConflictIndicators", () => {
  it("renders a conflict warning card", () => {
    render(
      <ConflictWarningCard
        conflictDetected
        agreementLevel="conflicting"
        conflictSummary="Two policy sources disagree on the leave allowance."
        preferredDocumentIds={["doc-a"]}
      />,
    );

    expect(screen.getByText("Source conflict detected")).toBeInTheDocument();
    expect(screen.getByText("Conflicting sources")).toBeInTheDocument();
    expect(screen.getByText("Preferred source IDs: doc-a")).toBeInTheDocument();
  });

  it("renders source comparison cards for preferred and conflicting citations", () => {
    const citations: ChatCitationResponse[] = [
      {
        document_id: "doc-a",
        chunk_id: "chunk-a",
        filename: "policy-a.pdf",
        conflict_status: "preferred",
        text_snippet: "Policy A states 20 days.",
      } as ChatCitationResponse,
      {
        document_id: "doc-b",
        chunk_id: "chunk-b",
        filename: "policy-b.pdf",
        conflict_status: "conflicting",
        text_snippet: "Policy B states 30 days.",
      } as ChatCitationResponse,
    ];

    render(
      <ConflictSourceComparison
        conflictDetected
        agreementLevel="conflicting"
        conflictSummary="Two policy sources disagree on the leave allowance."
        preferredDocumentIds={["doc-a"]}
        citations={citations}
      />,
    );

    expect(screen.getByText("Source comparison")).toBeInTheDocument();
    expect(screen.getByText("Preferred sources")).toBeInTheDocument();
    expect(screen.getAllByText("Conflicting sources").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Preferred")).toBeInTheDocument();
    expect(screen.getByText("Conflicting")).toBeInTheDocument();
  });
});
