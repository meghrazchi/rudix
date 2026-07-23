import { describe, expect, it } from "vitest";

import en from "./messages/en.json";
import de from "./messages/de.json";
import es from "./messages/es.json";
import fr from "./messages/fr.json";
import fa from "./messages/fa.json";
import ar from "./messages/ar.json";

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

function hasValidMessageValue(value: unknown): boolean {
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (typeof value === "boolean" || typeof value === "number") {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(hasValidMessageValue);
  }
  if (value !== null && typeof value === "object") {
    return Object.values(value).every(hasValidMessageValue);
  }
  return false;
}

const enKeys = collectLeafKeys(en as Record<string, unknown>);
const deKeys = collectLeafKeys(de as Record<string, unknown>);
const esKeys = collectLeafKeys(es as Record<string, unknown>);
const frKeys = collectLeafKeys(fr as Record<string, unknown>);
const faKeys = collectLeafKeys(fa as Record<string, unknown>);
const arKeys = collectLeafKeys(ar as Record<string, unknown>);

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

  it("fa.json contains all keys from en.json", () => {
    const missing = [...enKeys].filter((k) => !faKeys.has(k));
    expect(missing).toEqual([]);
  });

  it("ar.json contains all keys from en.json", () => {
    const missing = [...enKeys].filter((k) => !arKeys.has(k));
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

  it("no extra keys in fa.json not present in en.json", () => {
    const extra = [...faKeys].filter((k) => !enKeys.has(k));
    expect(extra).toEqual([]);
  });

  it("no extra keys in ar.json not present in en.json", () => {
    const extra = [...arKeys].filter((k) => !enKeys.has(k));
    expect(extra).toEqual([]);
  });

  it("all locale files have valid message values for all keys", () => {
    const localeFiles = [
      { name: "en", keys: enKeys, obj: en as Record<string, unknown> },
      { name: "de", keys: deKeys, obj: de as Record<string, unknown> },
      { name: "es", keys: esKeys, obj: es as Record<string, unknown> },
      { name: "fr", keys: frKeys, obj: fr as Record<string, unknown> },
      { name: "fa", keys: faKeys, obj: fa as Record<string, unknown> },
      { name: "ar", keys: arKeys, obj: ar as Record<string, unknown> },
    ];

    for (const { name, keys, obj } of localeFiles) {
      for (const key of keys) {
        const parts = key.split(".");
        let val: unknown = obj;
        for (const part of parts) {
          val = (val as Record<string, unknown>)[part];
        }
        expect(
          hasValidMessageValue(val),
          `${name}.json key "${key}" should contain valid message values`,
        ).toBe(true);
      }
    }
  });
});
