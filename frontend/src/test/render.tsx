import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import {
  clearSessionStorage,
  writeSessionToStorage,
  type AuthenticatedSession,
} from "@/lib/auth-session";

type RenderWithProvidersOptions = Omit<RenderOptions, "wrapper"> & {
  queryClient?: QueryClient;
  session?: AuthenticatedSession | null;
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
    ...renderOptions
  } = options;
  seedTestSession(session);

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
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
