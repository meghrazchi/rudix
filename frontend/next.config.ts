import type { NextConfig } from "next";

import { assertFrontendRuntimeConfigForBuild } from "./src/lib/runtime-config";

assertFrontendRuntimeConfigForBuild(process.env);

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
