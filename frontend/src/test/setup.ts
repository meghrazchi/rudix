import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { createElement, forwardRef, type AnchorHTMLAttributes } from "react";
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

vi.mock("next-intl/navigation", () => {
  const Link = forwardRef<
    HTMLAnchorElement,
    AnchorHTMLAttributes<HTMLAnchorElement>
  >(function MockNavigationLink({ children, ...props }, ref) {
    return createElement("a", { ...props, ref }, children);
  });

  function createNavigation() {
    return {
      Link,
      useRouter: () => ({
        push: vi.fn(),
        replace: vi.fn(),
        prefetch: vi.fn(),
        back: vi.fn(),
        forward: vi.fn(),
        refresh: vi.fn(),
      }),
      usePathname: () => "/",
      redirect: vi.fn(),
      permanentRedirect: vi.fn(),
    };
  }

  return {
    Link,
    createNavigation,
    useRouter: () => ({
      push: vi.fn(),
      replace: vi.fn(),
      prefetch: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
    }),
    usePathname: () => "/",
    redirect: vi.fn(),
    permanentRedirect: vi.fn(),
  };
});

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
  type Translator = ReturnType<typeof actual.createTranslator>;
  const translatorCache = new Map<string, Translator>();

  function getTranslator(namespace: string): Translator {
    const cached = translatorCache.get(namespace);
    if (cached) {
      return cached;
    }

    const translator = actual.createTranslator({
      locale: "en",
      messages,
      namespace,
    });
    translatorCache.set(namespace, translator);
    return translator;
  }

  afterEach(() => {
    translatorCache.clear();
  });

  return {
    ...actual,
    useTranslations: (namespace: string) => getTranslator(namespace),
    useLocale: () => "en",
    useFormatter: () => ({
      dateTime: (date: Date) => date.toISOString(),
      number: (n: number) => String(n),
      relativeTime: (date: Date) => date.toISOString(),
    }),
    NextIntlClientProvider: ({ children }: { children: React.ReactNode }) =>
      children,
    getTranslations: async (namespace: string) => getTranslator(namespace),
    getLocale: async () => "en",
    getMessages: async () => messages,
  };
});
