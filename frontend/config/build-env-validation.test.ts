import { describe, expect, it } from "vitest";

import { validateBuildEnvironment } from "./build-env-validation.mjs";

type Env = Record<string, string | undefined>;

const BASE: Env = {
  NEXT_PUBLIC_API_URL: "https://api.example.com/api/v1",
  NEXT_PUBLIC_APP_URL: "https://app.example.com",
};

const DEV_VARS: Record<string, string> = {
  NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "true",
  NEXT_PUBLIC_AUTH_LOCAL_PASSWORD: "s3cret-value",
  NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "tok-access",
  NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK: " TRUE ",
  NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_PASSWORD: "s3cret-signup",
  NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN: "tok-refresh",
};

function env(deployment: string, extra: Env = {}): Env {
  return { ...BASE, NEXT_PUBLIC_DEPLOYMENT_ENV: deployment, ...extra };
}

describe("validateBuildEnvironment", () => {
  it.each(["development", "test"])("allows every dev variable in %s", (e) => {
    const local = {
      NEXT_PUBLIC_API_URL: "http://localhost:8000/api/v1",
      NEXT_PUBLIC_APP_URL: "http://localhost:3000",
    };
    expect(validateBuildEnvironment(env(e, { ...local, ...DEV_VARS }))).toEqual(
      [],
    );
  });

  it.each(["staging", "production"])("accepts a clean %s env", (e) => {
    expect(validateBuildEnvironment(env(e))).toEqual([]);
  });

  describe.each(["staging", "production"])("%s", (e) => {
    it.each(Object.keys(DEV_VARS))(
      "rejects %s without echoing value",
      (key) => {
        const errors = validateBuildEnvironment(
          env(e, { [key]: DEV_VARS[key] }),
        );
        expect(errors).toHaveLength(1);
        expect(errors[0]).toContain(key);
        expect(errors[0]).toContain("development-only");
        expect(errors[0]).not.toContain(DEV_VARS[key].trim());
      },
    );

    it("allows false and empty values", () => {
      expect(
        validateBuildEnvironment(
          env(e, {
            NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "false",
            NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK: "",
            NEXT_PUBLIC_AUTH_LOCAL_PASSWORD: "",
            NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_PASSWORD: "  ",
            NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "",
            NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN: undefined,
          }),
        ),
      ).toEqual([]);
    });

    it("reports all variables together", () => {
      expect(validateBuildEnvironment(env(e, DEV_VARS))).toHaveLength(6);
    });
  });

  it("requires both URLs", () => {
    const errors = validateBuildEnvironment({});
    expect(errors).toEqual([
      "NEXT_PUBLIC_API_URL is required and must be an absolute http(s) URL.",
      "NEXT_PUBLIC_APP_URL is required and must be an absolute http(s) URL.",
    ]);
  });

  it("rejects invalid and non-http URLs", () => {
    expect(
      validateBuildEnvironment({
        NEXT_PUBLIC_API_URL: "not a url",
        NEXT_PUBLIC_APP_URL: "ftp://example.com",
      }),
    ).toEqual([
      "NEXT_PUBLIC_API_URL must be a valid absolute URL.",
      "NEXT_PUBLIC_APP_URL must use http:// or https://.",
    ]);
  });

  it("requires https in production-like environments", () => {
    const errors = validateBuildEnvironment(
      env("production", { NEXT_PUBLIC_APP_URL: "http://app.example.com" }),
    );
    expect(errors).toEqual([
      "NEXT_PUBLIC_APP_URL must use https:// when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.",
    ]);
  });

  it("rejects loopback hosts in production-like environments", () => {
    for (const host of ["localhost", "127.0.0.1", "[::1]", "x.localhost"]) {
      const errors = validateBuildEnvironment(
        env("staging", { NEXT_PUBLIC_API_URL: `https://${host}/api` }),
      );
      expect(errors).toEqual([
        "NEXT_PUBLIC_API_URL must not point to localhost when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.",
      ]);
    }
  });

  it("treats empty DEPLOYMENT_ENV with ENVIRONMENT=production as production-like", () => {
    const errors = validateBuildEnvironment({
      ...BASE,
      NEXT_PUBLIC_DEPLOYMENT_ENV: "",
      NEXT_PUBLIC_ENVIRONMENT: "production",
      NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "true",
    });
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("NEXT_PUBLIC_AUTH_LOCAL_FALLBACK");
  });
});
