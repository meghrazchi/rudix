import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { setRequestLocaleMock } = vi.hoisted(() => ({
  setRequestLocaleMock: vi.fn(),
}));

vi.mock("next-intl/server", () => ({
  setRequestLocale: setRequestLocaleMock,
}));

import { setRequestLocaleFromParams, useRequestLocale } from "./request-locale";

type LocaleParams = Promise<{ locale: string }>;

/** A promise React's `use` reads synchronously (already fulfilled). */
function fulfilledParams(locale: string): LocaleParams {
  const value = { locale };
  return Object.assign(Promise.resolve(value), {
    status: "fulfilled",
    value,
  });
}

function Probe({ params }: { params?: LocaleParams }) {
  useRequestLocale(params);
  return <p>rendered</p>;
}

describe("useRequestLocale", () => {
  beforeEach(() => {
    setRequestLocaleMock.mockReset();
  });

  it("sets the request locale from the route params", () => {
    const { getByText } = render(<Probe params={fulfilledParams("de")} />);
    expect(getByText("rendered")).toBeInTheDocument();
    expect(setRequestLocaleMock).toHaveBeenCalledWith("de");
  });

  it("ignores locales outside SUPPORTED_LOCALES", () => {
    render(<Probe params={fulfilledParams("xx")} />);
    expect(setRequestLocaleMock).not.toHaveBeenCalled();
  });

  it("is a no-op without route params (unit-test renders)", () => {
    render(<Probe />);
    expect(setRequestLocaleMock).not.toHaveBeenCalled();
  });
});

describe("setRequestLocaleFromParams", () => {
  beforeEach(() => {
    setRequestLocaleMock.mockReset();
  });

  it("awaits the params and sets the locale", async () => {
    await setRequestLocaleFromParams(Promise.resolve({ locale: "fa" }));
    expect(setRequestLocaleMock).toHaveBeenCalledWith("fa");
  });

  it("is a no-op without params", async () => {
    await setRequestLocaleFromParams(undefined);
    expect(setRequestLocaleMock).not.toHaveBeenCalled();
  });
});
