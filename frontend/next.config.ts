import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { assertFrontendRuntimeConfigForBuild } from "./src/lib/runtime-config";

if (process.env.NODE_ENV === "production") {
  assertFrontendRuntimeConfigForBuild();
}

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {};

export default withNextIntl(nextConfig);
