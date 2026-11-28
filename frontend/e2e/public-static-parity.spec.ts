import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import staticPublicRoutes from "../config/static-public-routes.json";
import { SUPPORTED_LOCALES } from "../src/i18n/routing";
import { buildLocalizedPublicPath } from "../src/lib/public-site/seo";

/**
 * Public page parity (R07-01, R07-02).
 *
 * The baseline was recorded once against the pre-0.7.0 rendering code with
 * PUBLIC_PARITY_UPDATE=1 and is never re-recorded in 0.7.0: a change that
 * alters it has changed what a public page shows (metadata, SEO tags or DOM),
 * not only how it renders.
 */

const BASELINE_PATH = path.join(
  __dirname,
  "fixtures",
  "public-parity-baseline.json",
);
const UPDATE = process.env.PUBLIC_PARITY_UPDATE === "1";

const EXTRA_PATHS = ["/status", "/forbidden", "/login"] as const;
const PATHS = [...staticPublicRoutes, ...EXTRA_PATHS];

type ParitySnapshot = {
  title: string;
  description: string | null;
  robots: string | null;
  canonical: string | null;
  alternates: Array<[string, string]>;
  openGraph: Array<[string, string]>;
  twitter: Array<[string, string]>;
  jsonLd: string[];
  htmlLang: string | null;
  htmlDir: string | null;
  mainTextSha256: string;
  mainStructureSha256: string;
};

type RawSnapshot = Omit<
  ParitySnapshot,
  "mainTextSha256" | "mainStructureSha256"
> & { mainText: string; mainStructure: string };

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

// The site origin comes from the environment (NEXT_PUBLIC_PUBLIC_SITE_URL or
// the app URL), so a local run and CI produce different absolute URLs for
// the same page. Local dev origins are compared as one placeholder; any
// other origin (a real domain, schema.org) still has to match exactly.
const LOCAL_ORIGIN = /https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?/g;

function normalizeOrigin(snapshot: ParitySnapshot): ParitySnapshot {
  // One pass over the serialized snapshot covers every field, JSON-LD included.
  return JSON.parse(
    JSON.stringify(snapshot).replace(LOCAL_ORIGIN, "{site-origin}"),
  ) as ParitySnapshot;
}

function readBaseline(): Record<string, ParitySnapshot> {
  if (!existsSync(BASELINE_PATH)) {
    return {};
  }
  return JSON.parse(readFileSync(BASELINE_PATH, "utf8")) as Record<
    string,
    ParitySnapshot
  >;
}

function writeBaselineEntry(key: string, snapshot: ParitySnapshot): void {
  // Read-merge-write per test so an interrupted run keeps earlier entries.
  const baseline = readBaseline();
  baseline[key] = snapshot;
  const sorted = Object.fromEntries(
    Object.keys(baseline)
      .sort()
      .map((entryKey) => [entryKey, baseline[entryKey]]),
  );
  writeFileSync(BASELINE_PATH, `${JSON.stringify(sorted, null, 2)}\n`);
}

async function captureSnapshot(page: Page): Promise<ParitySnapshot> {
  const raw: RawSnapshot = await page.evaluate(() => {
    const attr = (selector: string, name: string): string | null =>
      document.querySelector(selector)?.getAttribute(name) ?? null;
    const pairs = (selector: string, keyAttr: string, valueAttr: string) =>
      Array.from(document.querySelectorAll(selector)).map(
        (element) =>
          [
            element.getAttribute(keyAttr) ?? "",
            element.getAttribute(valueAttr) ?? "",
          ] as [string, string],
      );
    const main = document.querySelector("main");
    const structure = main
      ? Array.from(main.querySelectorAll("*"))
          .map(
            (element) =>
              `${element.tagName.toLowerCase()}.${element.getAttribute("class") ?? ""}`,
          )
          .join("\n")
      : "";

    return {
      title: document.title,
      description: attr('meta[name="description"]', "content"),
      robots: attr('meta[name="robots"]', "content"),
      canonical: attr('link[rel="canonical"]', "href"),
      alternates: pairs('link[rel="alternate"][hreflang]', "hreflang", "href"),
      openGraph: pairs('meta[property^="og:"]', "property", "content"),
      twitter: pairs('meta[name^="twitter:"]', "name", "content"),
      jsonLd: Array.from(
        document.querySelectorAll('script[type="application/ld+json"]'),
      ).map((script) => script.textContent ?? ""),
      htmlLang: document.documentElement.getAttribute("lang"),
      htmlDir: document.documentElement.getAttribute("dir"),
      mainText: main instanceof HTMLElement ? main.innerText : "",
      mainStructure: structure,
    };
  });

  const { mainText, mainStructure, ...rest } = raw;
  return {
    ...rest,
    mainTextSha256: sha256(mainText),
    mainStructureSha256: sha256(mainStructure),
  };
}

test.describe("public pages keep metadata, SEO tags and DOM", () => {
  const baseline = UPDATE ? {} : readBaseline();

  for (const locale of SUPPORTED_LOCALES) {
    for (const routePath of PATHS) {
      const localizedPath = buildLocalizedPublicPath(locale, routePath);

      test(`${localizedPath} matches the parity baseline`, async ({ page }) => {
        test.setTimeout(120_000);
        const missingMessages: string[] = [];
        page.on("console", (message) => {
          const text = message.text();
          if (text.includes("MISSING_MESSAGE")) {
            missingMessages.push(text);
          }
        });

        const response = await page.goto(localizedPath, {
          waitUntil: "load",
        });
        expect(response?.status(), localizedPath).toBeLessThan(400);
        await page.waitForLoadState("networkidle");

        const snapshot = await captureSnapshot(page);
        expect(missingMessages, `${localizedPath} console`).toEqual([]);

        if (UPDATE) {
          writeBaselineEntry(localizedPath, snapshot);
          return;
        }

        const expected = (baseline as Record<string, ParitySnapshot>)[
          localizedPath
        ];
        expect(expected, `${localizedPath} has a baseline entry`).toBeTruthy();
        expect(normalizeOrigin(snapshot)).toEqual(normalizeOrigin(expected));
      });
    }
  }
});
