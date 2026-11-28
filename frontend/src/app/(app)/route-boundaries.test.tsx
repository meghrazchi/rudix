import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { notFoundMock } = vi.hoisted(() => ({
  notFoundMock: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
vi.mock("next/navigation", () => ({ notFound: notFoundMock }));

import { SegmentRouteError } from "@/components/errors/RouteErrorFallback";

import AdminErrorProbePage from "./admin/error-probe/page";
import AdminError from "./admin/error";
import AdminLoading from "./admin/loading";
import ChatError from "./chat/error";
import ChatLoading from "./chat/loading";
import CollectionsError from "./collections/error";
import CollectionsLoading from "./collections/loading";
import DocumentsError from "./documents/error";
import DocumentsLoading from "./documents/loading";
import ReportsError from "./reports/error";
import ReportsLoading from "./reports/loading";
import SettingsError from "./settings/error";
import SettingsLoading from "./settings/loading";

afterEach(() => {
  vi.unstubAllEnvs();
  notFoundMock.mockClear();
});

describe("segment error and loading files", () => {
  it("re-export the inline route error fallback", () => {
    for (const component of [
      AdminError,
      ChatError,
      CollectionsError,
      DocumentsError,
      ReportsError,
      SettingsError,
    ]) {
      expect(component).toBe(SegmentRouteError);
    }
  });

  it.each([
    AdminLoading,
    ChatLoading,
    CollectionsLoading,
    DocumentsLoading,
    ReportsLoading,
    SettingsLoading,
  ])("loading file %# renders a skeleton", (Loading) => {
    render(<Loading />);
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });
});

describe("/admin/error-probe", () => {
  it("is a 404 unless the e2e flag is set", () => {
    vi.stubEnv("NEXT_PUBLIC_E2E_ERROR_PROBE", "");
    expect(() => AdminErrorProbePage()).toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalledTimes(1);
  });

  it("throws during render when the e2e flag is set", () => {
    vi.stubEnv("NEXT_PUBLIC_E2E_ERROR_PROBE", "true");
    expect(() => AdminErrorProbePage()).toThrow("E2E error probe");
    expect(notFoundMock).not.toHaveBeenCalled();
  });
});
