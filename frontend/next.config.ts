import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  /* config options here */
};

export default async function config(phase: string): Promise<NextConfig> {
  if (phase === PHASE_PRODUCTION_BUILD) {
    const { assertFrontendRuntimeConfigForBuild } = await import(
      "./src/lib/runtime-config"
    );
    assertFrontendRuntimeConfigForBuild(process.env);
  }
  return withNextIntl(nextConfig);
}
