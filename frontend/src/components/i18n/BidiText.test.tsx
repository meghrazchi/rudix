import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BidiText, TechnicalText } from "./BidiText";

describe("bidi text primitives", () => {
  it("lets mixed user content determine its own direction", () => {
    render(<BidiText>تقرير Rudix 2026</BidiText>);

    expect(screen.getByText("تقرير Rudix 2026")).toHaveAttribute("dir", "auto");
  });

  it("keeps technical identifiers left-to-right", () => {
    render(<TechnicalText>https://rudix.example/api/v1?q=سلام</TechnicalText>);

    expect(
      screen.getByText("https://rudix.example/api/v1?q=سلام"),
    ).toHaveAttribute("dir", "ltr");
  });
});
