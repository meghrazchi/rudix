import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OnboardingCtaBanner } from "@/components/onboarding/OnboardingCtaBanner";

describe("OnboardingCtaBanner", () => {
  it("renders title and description", () => {
    render(
      <OnboardingCtaBanner
        title="Upload your first document"
        description="Add a PDF, DOCX, or text file to your knowledge base."
        actionLabel="Go to Documents"
        actionHref="/documents"
      />,
    );
    expect(screen.getByText("Upload your first document")).toBeInTheDocument();
    expect(
      screen.getByText("Add a PDF, DOCX, or text file to your knowledge base."),
    ).toBeInTheDocument();
  });

  it("renders a link action when actionHref is provided", () => {
    render(
      <OnboardingCtaBanner
        title="Upload your first document"
        description="Add files to your knowledge base."
        actionLabel="Go to Documents"
        actionHref="/documents"
      />,
    );
    const link = screen.getByRole("link", { name: /go to documents/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/documents");
  });

  it("calls onAction callback when action button is clicked", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <OnboardingCtaBanner
        title="Ask a question"
        description="Chat with your knowledge base."
        actionLabel="Open Chat"
        onAction={onAction}
      />,
    );
    await user.click(screen.getByRole("button", { name: /open chat/i }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("renders secondary link when secondaryLabel and secondaryHref are provided", () => {
    render(
      <OnboardingCtaBanner
        title="Invite your team"
        description="Add members to collaborate."
        actionLabel="Manage team"
        actionHref="/settings?tab=organization"
        secondaryLabel="Learn more"
        secondaryHref="/docs/team"
      />,
    );
    expect(screen.getByRole("link", { name: /manage team/i })).toHaveAttribute(
      "href",
      "/settings?tab=organization",
    );
    expect(screen.getByRole("link", { name: /learn more/i })).toHaveAttribute(
      "href",
      "/docs/team",
    );
  });
});
