import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Default stub for next/navigation. Individual test files may override this.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
  useSearchParams: () => ({
    get: () => null,
    has: () => false,
    toString: () => "",
  }),
  usePathname: () => "/",
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

afterEach(() => {
  cleanup();
});

// Provide next-intl translations in test environment using actual English messages.
// This keeps existing tests working without modification while enabling i18n in new tests.
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const messages = (await import("@/i18n/messages/en.json")).default as Record<
    string,
    unknown
  >;

  function getNestedValue(
    obj: Record<string, unknown>,
    path: string,
  ): string | undefined {
    const parts = path.split(".");
    let current: unknown = obj;
    for (const part of parts) {
      if (current === null || typeof current !== "object") return undefined;
      current = (current as Record<string, unknown>)[part];
    }
    return typeof current === "string" ? current : undefined;
  }

  function makeTranslator(namespace: string) {
    return function translate(
      key: string,
      values?: Record<string, unknown>,
    ): string {
      const fullKey = `${namespace}.${key}`;
      const raw = getNestedValue(messages, fullKey) ?? key;
      if (!values) return raw;
      return raw.replace(/\{(\w+)\}/g, (_, name) =>
        values[name] !== undefined ? String(values[name]) : `{${name}}`,
      );
    };
  }

  return {
    ...actual,
    useTranslations: (namespace: string) => makeTranslator(namespace),
    useLocale: () => "en",
    useFormatter: () => ({
      dateTime: (date: Date) => date.toISOString(),
      number: (n: number) => String(n),
      relativeTime: (date: Date) => date.toISOString(),
    }),
    NextIntlClientProvider: ({ children }: { children: React.ReactNode }) =>
      children,
    getTranslations: async (namespace: string) => makeTranslator(namespace),
    getLocale: async () => "en",
    getMessages: async () => messages,
  };
});
