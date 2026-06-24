import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "./LanguageSwitcher";
import { LOCALE_COOKIE_NAME } from "@/i18n/routing";

const mockRefresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: mockRefresh,
  }),
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({
    replace: (_path: string, options?: { locale?: string }) => {
      if (options?.locale) {
        document.cookie = `NEXT_LOCALE=${options.locale}; path=/`;
        mockRefresh();
      }
    },
  }),
  usePathname: () => "/",
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => {
    const labels: Record<string, string> = {
      ariaLabel: "Select display language",
      label: "Language",
      en: "English",
      de: "German",
      es: "Spanish",
      fr: "French",
    };
    return labels[key] ?? key;
  },
  useLocale: () => "en",
}));

describe("LanguageSwitcher (select variant)", () => {
  beforeEach(() => {
    mockRefresh.mockReset();
    document.cookie = `${LOCALE_COOKIE_NAME}=en; path=/`;
  });

  it("renders a select with all four locale options", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox", {
      name: "Select display language",
    });
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /English/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /German/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Spanish/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /French/ })).toBeInTheDocument();
  });

  it("shows the current locale as selected", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("en");
  });

  it("sets locale cookie and refreshes on change", async () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox");

    await userEvent.selectOptions(select, "de");

    expect(document.cookie).toContain(`${LOCALE_COOKIE_NAME}=de`);
    expect(mockRefresh).toHaveBeenCalled();
  });
});

describe("LanguageSwitcher (buttons variant)", () => {
  beforeEach(() => {
    mockRefresh.mockReset();
    document.cookie = `${LOCALE_COOKIE_NAME}=en; path=/`;
  });

  it("renders one button per locale", () => {
    render(<LanguageSwitcher variant="buttons" />);
    expect(screen.getByRole("button", { name: /EN/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /DE/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ES/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /FR/ })).toBeInTheDocument();
  });

  it("marks the current locale button with aria-current", () => {
    render(<LanguageSwitcher variant="buttons" />);
    const enButton = screen.getByRole("button", { name: /EN/ });
    expect(enButton).toHaveAttribute("aria-current", "true");
  });

  it("sets locale cookie and refreshes when a different locale is clicked", async () => {
    render(<LanguageSwitcher variant="buttons" />);
    await userEvent.click(screen.getByRole("button", { name: /FR/ }));

    expect(document.cookie).toContain(`${LOCALE_COOKIE_NAME}=fr`);
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("does not refresh when current locale button is clicked", async () => {
    render(<LanguageSwitcher variant="buttons" />);
    await userEvent.click(screen.getByRole("button", { name: /EN/ }));
    expect(mockRefresh).not.toHaveBeenCalled();
  });
});
