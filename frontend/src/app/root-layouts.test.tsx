import { isValidElement, type ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { serverMock, notFoundMock } = vi.hoisted(() => ({
  serverMock: {
    setRequestLocale: vi.fn(),
    getLocale: vi.fn(),
    getMessages: vi.fn(),
  },
  notFoundMock: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

vi.mock("next-intl/server", () => serverMock);
vi.mock("next/navigation", () => ({ notFound: notFoundMock }));

import LocaleLayout, {
  dynamicParams,
  generateStaticParams,
  metadata as localeMetadata,
} from "./[locale]/layout";
import AuthenticatedLayout, { metadata as appMetadata } from "./(app)/layout";
import GlobalNotFound, {
  metadata as notFoundMetadata,
} from "./global-not-found";
import LocaleError from "./[locale]/error";
import AppError from "./(app)/error";
import AppNotFound from "./(app)/not-found";
import RouteErrorFallback from "@/components/errors/RouteErrorFallback";
import { RootDocument } from "@/components/layout/RootDocument";
import { ProtectedAppLayout } from "@/components/layout/ProtectedAppLayout";
import { NotFoundPage } from "@/components/public/pages/NotFoundPage";
import enMessages from "@/i18n/messages/en.json";
import frMessages from "@/i18n/messages/fr.json";
import { APP_NAMESPACES, PUBLIC_NAMESPACES } from "@/i18n/namespaces";
import { SUPPORTED_LOCALES } from "@/i18n/routing";
import { ROOT_METADATA } from "@/lib/root-metadata";

type RootDocumentElement = ReactElement<{
  locale: string;
  messages: Record<string, unknown>;
  children: unknown;
}>;

function expectRootDocument(element: unknown): RootDocumentElement {
  expect(isValidElement(element)).toBe(true);
  const root = element as RootDocumentElement;
  expect(root.type).toBe(RootDocument);
  return root;
}

beforeEach(() => {
  serverMock.setRequestLocale.mockReset();
  serverMock.getLocale.mockReset();
  serverMock.getMessages.mockReset();
  notFoundMock.mockClear();
});

describe("app/[locale]/layout.tsx (public root layout)", () => {
  it("prerenders one static page per supported locale", () => {
    expect(generateStaticParams()).toEqual(
      SUPPORTED_LOCALES.map((locale) => ({ locale })),
    );
    expect(dynamicParams).toBe(false);
    expect(localeMetadata).toBe(ROOT_METADATA);
  });

  it("sets the request locale and ships only the public namespaces", async () => {
    const root = expectRootDocument(
      await LocaleLayout({
        children: <p>page</p>,
        params: Promise.resolve({ locale: "fr" }),
      }),
    );

    expect(serverMock.setRequestLocale).toHaveBeenCalledWith("fr");
    expect(root.props.locale).toBe("fr");
    expect(Object.keys(root.props.messages)).toEqual([...PUBLIC_NAMESPACES]);
    expect(root.props.messages.public).toEqual(frMessages.public);
    expect(root.props.messages).not.toHaveProperty("adminPermissions");
  });

  it("answers 404 for an unknown locale", async () => {
    await expect(
      LocaleLayout({
        children: <p>page</p>,
        params: Promise.resolve({ locale: "xx" }),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(serverMock.setRequestLocale).not.toHaveBeenCalled();
  });
});

describe("app/(app)/layout.tsx (signed-in root layout)", () => {
  it("uses the cookie locale and the app namespaces", async () => {
    serverMock.getLocale.mockResolvedValue("de");
    serverMock.getMessages.mockResolvedValue(enMessages);

    const root = expectRootDocument(
      await AuthenticatedLayout({ children: <p>app</p> }),
    );

    expect(appMetadata).toBe(ROOT_METADATA);
    expect(root.props.locale).toBe("de");
    expect(Object.keys(root.props.messages)).toEqual([...APP_NAMESPACES]);
    const shell = root.props.children as ReactElement;
    expect(shell.type).toBe(ProtectedAppLayout);
  });
});

describe("app/global-not-found.tsx", () => {
  it("renders NotFoundPage in the request locale with public namespaces", async () => {
    serverMock.getLocale.mockResolvedValue("fr");

    const root = expectRootDocument(await GlobalNotFound());

    expect(notFoundMetadata).toBe(ROOT_METADATA);
    expect(root.props.locale).toBe("fr");
    expect(Object.keys(root.props.messages)).toEqual([...PUBLIC_NAMESPACES]);
    expect(root.props.messages.errors).toEqual(frMessages.errors);
    expect((root.props.children as ReactElement).type).toBe(NotFoundPage);
  });
});

describe("segment error and not-found files", () => {
  it("re-export the shared route error fallback", () => {
    expect(LocaleError).toBe(RouteErrorFallback);
    expect(AppError).toBe(RouteErrorFallback);
  });

  it("(app)/not-found renders NotFoundPage", () => {
    expect((AppNotFound() as ReactElement).type).toBe(NotFoundPage);
  });
});
