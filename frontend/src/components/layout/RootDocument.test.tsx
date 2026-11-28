import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const { configErrors } = vi.hoisted(() => ({
  configErrors: { current: [] as string[] },
}));

vi.mock("@/lib/runtime-config", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runtime-config")>()),
  getFrontendRuntimeConfigErrors: () => configErrors.current,
}));

import { RootDocument } from "./RootDocument";

afterEach(() => {
  configErrors.current = [];
});

describe("RootDocument", () => {
  it("renders the html document with locale attributes and children, without a third-party font link", () => {
    const html = renderToStaticMarkup(
      <RootDocument locale="de" messages={{}}>
        <p>child content</p>
      </RootDocument>,
    );

    expect(html).toContain(
      '<html lang="de-DE" dir="ltr" class="h-full antialiased">',
    );
    expect(html).not.toContain("fonts.googleapis.com");
    expect(html).toContain('<body class="flex min-h-full flex-col">');
    expect(html).toContain("<p>child content</p>");
    expect(html).not.toContain("Frontend configuration is incomplete");
  });

  it("sets rtl direction for right-to-left locales", () => {
    const html = renderToStaticMarkup(
      <RootDocument locale="fa" messages={{}}>
        <p>x</p>
      </RootDocument>,
    );
    expect(html).toContain('<html lang="fa" dir="rtl"');
  });

  it("shows the configuration banner instead of the app when config is invalid", () => {
    configErrors.current = ["NEXT_PUBLIC_API_URL is required."];
    const html = renderToStaticMarkup(
      <RootDocument locale="en" messages={{}}>
        <p>child content</p>
      </RootDocument>,
    );

    expect(html).toContain("Frontend configuration is incomplete");
    expect(html).toContain("<li>NEXT_PUBLIC_API_URL is required.</li>");
    expect(html).not.toContain("child content");
  });
});
