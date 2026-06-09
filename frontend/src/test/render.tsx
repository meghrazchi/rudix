import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";

import {
  clearSessionStorage,
  writeSessionToStorage,
  type AuthenticatedSession,
} from "@/lib/auth-session";
import type { SupportedLocale } from "@/i18n/routing";
import enMessages from "@/i18n/messages/en.json";

type RenderWithProvidersOptions = Omit<RenderOptions, "wrapper"> & {
  queryClient?: QueryClient;
  session?: AuthenticatedSession | null;
  locale?: SupportedLocale;
};

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function seedTestSession(session: AuthenticatedSession | null): void {
  if (!session) {
    clearSessionStorage();
    return;
  }
  writeSessionToStorage(session);
}

export function clearTestSession(): void {
  clearSessionStorage();
}

export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
) {
  const {
    queryClient = createTestQueryClient(),
    session = null,
    locale = "en",
    ...renderOptions
  } = options;
  seedTestSession(session);

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <NextIntlClientProvider locale={locale} messages={enMessages}>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  }

  return {
    queryClient,
    ...render(ui, {
      wrapper: Wrapper,
      ...renderOptions,
    }),
  };
}
