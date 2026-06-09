import { describe, expect, it } from "vitest";

import en from "./messages/en.json";
import de from "./messages/de.json";
import es from "./messages/es.json";
import fr from "./messages/fr.json";

function collectLeafKeys(
  obj: Record<string, unknown>,
  prefix = "",
): Set<string> {
  const keys = new Set<string>();
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      for (const nested of collectLeafKeys(
        value as Record<string, unknown>,
        fullKey,
      )) {
        keys.add(nested);
      }
    } else {
      keys.add(fullKey);
    }
  }
  return keys;
}

const enKeys = collectLeafKeys(en as Record<string, unknown>);
const deKeys = collectLeafKeys(de as Record<string, unknown>);
const esKeys = collectLeafKeys(es as Record<string, unknown>);
const frKeys = collectLeafKeys(fr as Record<string, unknown>);

describe("Message key parity across locales", () => {
  it("de.json contains all keys from en.json", () => {
    const missing = [...enKeys].filter((k) => !deKeys.has(k));
    expect(missing).toEqual([]);
  });

  it("es.json contains all keys from en.json", () => {
    const missing = [...enKeys].filter((k) => !esKeys.has(k));
    expect(missing).toEqual([]);
  });

  it("fr.json contains all keys from en.json", () => {
    const missing = [...enKeys].filter((k) => !frKeys.has(k));
    expect(missing).toEqual([]);
  });

  it("no extra keys in de.json not present in en.json", () => {
    const extra = [...deKeys].filter((k) => !enKeys.has(k));
    expect(extra).toEqual([]);
  });

  it("no extra keys in es.json not present in en.json", () => {
    const extra = [...esKeys].filter((k) => !enKeys.has(k));
    expect(extra).toEqual([]);
  });

  it("no extra keys in fr.json not present in en.json", () => {
    const extra = [...frKeys].filter((k) => !enKeys.has(k));
    expect(extra).toEqual([]);
  });

  it("all locale files have non-empty string values for all keys", () => {
    const localeFiles = [
      { name: "en", keys: enKeys, obj: en as Record<string, unknown> },
      { name: "de", keys: deKeys, obj: de as Record<string, unknown> },
      { name: "es", keys: esKeys, obj: es as Record<string, unknown> },
      { name: "fr", keys: frKeys, obj: fr as Record<string, unknown> },
    ];

    for (const { name, keys, obj } of localeFiles) {
      for (const key of keys) {
        const parts = key.split(".");
        let val: unknown = obj;
        for (const part of parts) {
          val = (val as Record<string, unknown>)[part];
        }
        expect(
          typeof val === "string" && val.trim().length > 0,
          `${name}.json key "${key}" should be a non-empty string`,
        ).toBe(true);
      }
    }
  });
});
