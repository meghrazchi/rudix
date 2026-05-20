import { vi, type Mock } from "vitest";

export type MockNavigationState = {
  pathname: string;
  searchParams: URLSearchParams;
  push: Mock;
  replace: Mock;
  prefetch: Mock;
  refresh: Mock;
  back: Mock;
};

export function createMockNavigationState(
  initial: Partial<Pick<MockNavigationState, "pathname" | "searchParams">> = {},
): MockNavigationState {
  return {
    pathname: initial.pathname ?? "/",
    searchParams: initial.searchParams ?? new URLSearchParams(),
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
  };
}

export function buildNextNavigationMock(state: MockNavigationState) {
  return {
    usePathname: () => state.pathname,
    useSearchParams: () => state.searchParams,
    useRouter: () => ({
      push: state.push,
      replace: state.replace,
      prefetch: state.prefetch,
      refresh: state.refresh,
      back: state.back,
    }),
  };
}
