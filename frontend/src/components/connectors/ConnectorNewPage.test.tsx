import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConnectorNewPage } from "@/components/connectors/ConnectorNewPage";

const mockSetupPage = vi.hoisted(() => ({
  render: vi.fn(),
}));

vi.mock("@/components/connectors/ConnectorSetupPage", () => ({
  ConnectorSetupPage: ({ providerKey }: { providerKey: string }) => {
    mockSetupPage.render(providerKey);
    return <div data-testid="connector-setup-page">{providerKey}</div>;
  },
}));

describe("ConnectorNewPage", () => {
  it("renders the shared setup page for Confluence", () => {
    render(<ConnectorNewPage providerKey="confluence" />);
    expect(screen.getByTestId("connector-setup-page")).toHaveTextContent(
      "confluence",
    );
    expect(mockSetupPage.render).toHaveBeenCalledWith("confluence");
  });
});
