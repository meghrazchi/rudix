import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    passWithNoTests: true,
    exclude: ["e2e/**", "test-results/**", ".next/**", "node_modules/**"],
  },
});
