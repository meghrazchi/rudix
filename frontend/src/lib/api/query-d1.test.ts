import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/api/query";

// Each factory must return exactly the array literal the component used
// before the key moved into the shared factory (R07-10).
describe("queryKeys (D1 settings factories)", () => {
  it("securityAudit matches the former literal", () => {
    expect(queryKeys.securityAudit).toEqual(["security", "audit"]);
  });

  it("adminTeam keys match the former literals", () => {
    const k = queryKeys.adminTeam;
    expect(k.all).toEqual(["admin", "team"]);
    expect(k.membersAll).toEqual(["admin", "team", "members"]);
    expect(k.invitations).toEqual(["admin", "team", "invitations"]);
    expect(k.members(20, 40, "ann", "admin", "active")).toEqual([
      "admin",
      "team",
      "members",
      20,
      40,
      "ann",
      "admin",
      "active",
    ]);
  });

  it("evaluationSetsList matches the former literal", () => {
    expect(queryKeys.evaluationSetsList).toEqual(["evaluation-sets-list"]);
  });

  it("profile and preference keys match the former literals", () => {
    expect(queryKeys.profileMe).toEqual(["profile", "me"]);
    expect(queryKeys.settingsPreferences).toEqual(["settings", "preferences"]);
  });
});

describe("queryKeys (D1 factories)", () => {
  it("adminPermissions keys match the former literals", () => {
    const k = queryKeys.adminPermissions;
    expect(k.roleMatrix).toEqual(["admin", "permissions", "role-matrix"]);
    expect(k.grants).toEqual(["admin", "permissions", "grants"]);
    expect(k.denies).toEqual(["admin", "permissions", "denies"]);
    expect(k.conflicts).toEqual(["admin", "permissions", "conflicts"]);
    expect(k.resourceAccess("grant", "document", "active")).toEqual([
      ...["admin", "permissions", "grants"],
      "document",
      "active",
    ]);
    expect(k.resourceAccess("deny", "", "")).toEqual([
      "admin",
      "permissions",
      "denies",
      "",
      "",
    ]);
    expect(k.conflict("c1")).toEqual([
      "admin",
      "permissions",
      "conflicts",
      "c1",
    ]);
    expect(k.conflictList("high", "open", "document")).toEqual([
      "admin",
      "permissions",
      "conflicts",
      "high",
      "open",
      "document",
    ]);
  });
});
