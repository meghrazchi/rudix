import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SubprocessorsRoute from "./page";

describe("Subprocessors page", () => {
  it("renders the page heading", () => {
    render(<SubprocessorsRoute />);
    expect(
      screen.getByRole("heading", { name: /subprocessors/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<SubprocessorsRoute />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<SubprocessorsRoute />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("lists AI model provider subprocessors", () => {
    render(<SubprocessorsRoute />);
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
  });

  it("lists infrastructure subprocessors", () => {
    render(<SubprocessorsRoute />);
    expect(screen.getByText(/MinIO/i)).toBeInTheDocument();
    expect(screen.getByText(/Qdrant/i)).toBeInTheDocument();
    expect(screen.getByText(/PostgreSQL/i)).toBeInTheDocument();
  });

  it("renders the subprocessors table", () => {
    render(<SubprocessorsRoute />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /subprocessor/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /purpose/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /location/i }),
    ).toBeInTheDocument();
  });

  it("renders the public header and footer", () => {
    render(<SubprocessorsRoute />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
