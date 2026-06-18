import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  AccessBadge,
  PermissionDeniedBadge,
  ReadOnlyBadge,
} from "@/components/layout/AccessBadge";

describe("AccessBadge", () => {
  it("renders owner badge with default label", () => {
    render(<AccessBadge type="owner" />);
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("renders denied badge with default label", () => {
    render(<AccessBadge type="denied" />);
    expect(screen.getByText("No access")).toBeInTheDocument();
  });

  it("renders read-only badge", () => {
    render(<AccessBadge type="read-only" />);
    expect(screen.getByText("Read only")).toBeInTheDocument();
  });

  it("uses custom label when provided", () => {
    render(<AccessBadge type="assigned" label="Org member" />);
    expect(screen.getByText("Org member")).toBeInTheDocument();
  });

  it("includes accessible aria-label", () => {
    render(<AccessBadge type="admin" />);
    expect(screen.getByLabelText("Access: Admin")).toBeInTheDocument();
  });

  it("renders collection-granted badge", () => {
    render(<AccessBadge type="collection-granted" />);
    expect(screen.getByText("Collection")).toBeInTheDocument();
  });

  it("renders connector-acl badge", () => {
    render(<AccessBadge type="connector-acl" />);
    expect(screen.getByText("Connector ACL")).toBeInTheDocument();
  });

  it("renders inherited badge", () => {
    render(<AccessBadge type="inherited" />);
    expect(screen.getByText("Inherited")).toBeInTheDocument();
  });
});

describe("PermissionDeniedBadge", () => {
  it("renders with default reason", () => {
    render(<PermissionDeniedBadge />);
    expect(screen.getByText("No access")).toBeInTheDocument();
  });

  it("renders with custom reason", () => {
    render(<PermissionDeniedBadge reason="Billing only" />);
    expect(screen.getByText("Billing only")).toBeInTheDocument();
  });
});

describe("ReadOnlyBadge", () => {
  it("renders default read-only label", () => {
    render(<ReadOnlyBadge />);
    expect(screen.getByText("Read only")).toBeInTheDocument();
  });

  it("renders with custom label", () => {
    render(<ReadOnlyBadge label="View only" />);
    expect(screen.getByText("View only")).toBeInTheDocument();
  });
});
