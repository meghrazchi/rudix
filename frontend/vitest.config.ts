import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "next/navigation": path.resolve(
        __dirname,
        "./node_modules/next/navigation.js",
      ),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    passWithNoTests: true,
    exclude: [
      "e2e/**",
      "e2e-integration/**",
      "test-results/**",
      ".next/**",
      ".next-e2e-ws/**",
      ".next-e2e-gate/**",
      ".next-e2e-runtime/**",
      "node_modules/**",
    ],
    // Coverage ratchet (R03-02): thresholds are the measured figures rounded down to one
    // decimal. Raise them when coverage rises; never lower them without a reason in the MR.
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "json-summary"],
      include: ["src/**"],
      exclude: [
        "src/lib/api/generated/**",
        "src/test/**",
        "**/__tests__/**",
        "**/tests/**",
        "**/*.test.{ts,tsx}",
        "**/*.spec.{ts,tsx}",
        "e2e/**",
        "e2e-integration/**",
        "**/*.stories.{ts,tsx}",
        "**/*.d.ts",
      ],
      thresholds: {
        lines: 69.5,
        functions: 62.1,
        branches: 60.8,
        statements: 68.6,
      },
    },
  },
});
