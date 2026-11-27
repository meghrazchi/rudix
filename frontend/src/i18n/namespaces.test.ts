import { describe, expect, it } from "vitest";

import de from "./messages/de.json";
import en from "./messages/en.json";
import { pickMessages } from "./messages";
import {
  ALL_NAMESPACES,
  APP_NAMESPACES,
  PUBLIC_NAMESPACES,
} from "./namespaces";

describe("message namespaces", () => {
  it("ALL_NAMESPACES mirrors the top-level keys of en.json", () => {
    expect(ALL_NAMESPACES).toEqual(Object.keys(en));
  });

  it("lists only namespaces that exist, without duplicates", () => {
    for (const list of [PUBLIC_NAMESPACES, APP_NAMESPACES]) {
      expect(new Set(list).size).toBe(list.length);
      for (const namespace of list) {
        expect(ALL_NAMESPACES).toContain(namespace);
      }
    }
  });

  it("PUBLIC_NAMESPACES and APP_NAMESPACES together cover every namespace", () => {
    const covered = new Set<string>([...PUBLIC_NAMESPACES, ...APP_NAMESPACES]);
    expect(ALL_NAMESPACES.filter((name) => !covered.has(name))).toEqual([]);
  });

  it("keeps the public payload free of app-only namespaces", () => {
    expect(PUBLIC_NAMESPACES).not.toContain("adminPermissions");
    expect(PUBLIC_NAMESPACES).not.toContain("chat");
    expect(PUBLIC_NAMESPACES).not.toContain("settings");
  });
});

describe("pickMessages", () => {
  it("keeps only the listed namespaces, by reference", () => {
    const picked = pickMessages(en, ["public", "errors"]);
    expect(Object.keys(picked)).toEqual(["public", "errors"]);
    expect(picked.public).toBe(en.public);
  });

  it("ignores names that are not in the catalogue", () => {
    expect(pickMessages(de, ["errors", "doesNotExist"])).toEqual({
      errors: de.errors,
    });
  });

  it("returns an empty object for an empty list", () => {
    expect(pickMessages(en, [])).toEqual({});
  });
});
