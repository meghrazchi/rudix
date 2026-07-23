import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LocaleDocumentAttributes } from "./LocaleDocumentAttributes";

describe("LocaleDocumentAttributes", () => {
  it("applies RTL attributes for Persian public routes", () => {
    const { container } = render(
      <LocaleDocumentAttributes locale="fa">
        <main>محتوا</main>
      </LocaleDocumentAttributes>,
    );

    expect(document.documentElement).toHaveAttribute("lang", "fa");
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    expect(container.firstElementChild).toHaveAttribute("lang", "fa");
    expect(container.firstElementChild).toHaveAttribute("dir", "rtl");
  });

  it("returns to LTR attributes after switching to English", () => {
    const { container, rerender } = render(
      <LocaleDocumentAttributes locale="fa">
        <main>محتوا</main>
      </LocaleDocumentAttributes>,
    );

    rerender(
      <LocaleDocumentAttributes locale="en">
        <main>Content</main>
      </LocaleDocumentAttributes>,
    );

    expect(document.documentElement).toHaveAttribute("lang", "en-US");
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    expect(container.firstElementChild).toHaveAttribute("lang", "en-US");
    expect(container.firstElementChild).toHaveAttribute("dir", "ltr");
  });
});
