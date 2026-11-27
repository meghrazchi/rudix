import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ProductOverviewPage } from "@/components/public/pages/ProductOverviewPage";
import en from "@/i18n/messages/en.json";

vi.mock("@/components/public/PublicActionLink", () => ({
  PublicActionLink: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

function renderProduct() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <ProductOverviewPage />
    </NextIntlClientProvider>,
  );
}

describe("ProductOverviewPage", () => {
  it("renders one h1 with the highlighted phrase inside it", () => {
    renderProduct();

    const [h1] = screen.getAllByRole("heading", { level: 1 });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(h1).toHaveTextContent(
      "The Infrastructure for High-Fidelity Document Intelligence",
    );
  });

  it("does not show unsupported performance numbers", () => {
    const { container } = renderProduct();

    for (const value of ["98.4%", "840ms", "0.96"]) {
      expect(container).not.toHaveTextContent(value);
    }
  });

  it("lists every pipeline stage in order", () => {
    renderProduct();

    const timeline = screen.getByRole("figure", {
      name: en.public.product.pipeline.imageAlt,
    });
    const stages = within(timeline)
      .getAllByRole("listitem")
      .map((item) => item.querySelector("p")?.textContent);
    expect(stages).toEqual([
      "Upload",
      "Extract",
      "Chunk",
      "Embed",
      "Retrieve",
      "Answer",
    ]);
  });

  it("keeps admin shortcuts and final CTAs pointed at their routes", () => {
    renderProduct();

    expect(screen.getByRole("link", { name: /Audit Logs/ })).toHaveAttribute(
      "href",
      "/admin/audit-logs",
    );
    expect(
      screen.getByRole("link", { name: /View Security Page/ }),
    ).toHaveAttribute("href", "/security");
  });

  it("renders FAQ answers in the markup for crawlers", () => {
    renderProduct();

    const faq = screen.getByRole("region", { name: "Product FAQ" });
    expect(within(faq).getAllByRole("group")).toHaveLength(5);
    expect(
      within(faq).getByText(en.public.product.faq.fileTypesA),
    ).toBeInTheDocument();
  });
});
