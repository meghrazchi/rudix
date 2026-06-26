import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { assertFrontendRuntimeConfigForBuild } from "./src/lib/runtime-config";

assertFrontendRuntimeConfigForBuild(process.env);

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  /* config options here */
};

export default withNextIntl(nextConfig);
