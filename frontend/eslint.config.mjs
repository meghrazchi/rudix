import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    ".next-e2e-ws/**",
    ".next-e2e-main/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      // React Hook Form's watch() is intentionally used and cannot be made
      // compatible with the React Compiler — suppress globally.
      "react-hooks/incompatible-library": "off",
    },
  },
  {
    // R07-12: no literal UI strings in translated areas; use useTranslations.
    files: [
      "src/components/chat/**/*.tsx",
      "src/components/evaluations/**/*.tsx",
      "src/components/states/**/*.tsx",
    ],
    ignores: [
      "**/*.test.tsx",
      "**/tests/**",
      "src/components/chat/SourceScopeSelector.tsx",
      "src/components/chat/ScopeControls.tsx",
      "src/components/chat/ScopeConnectorSection.tsx",
      "src/components/chat/DocumentPreviewModal*",
      "src/components/chat/TrustPanelModal*",
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          // Icon-font glyph names (lowercase_snake, e.g. open_in_new) are not UI text.
          selector:
            "JSXText[value=/[A-Za-z]{2,}/]:not([value=/^\\s*[a-z0-9_]+\\s*$/])",
          message:
            "Literal UI text is not allowed here; use useTranslations (R07-12).",
        },
        {
          selector:
            "JSXAttribute[name.name=/^(aria-label|title|placeholder|alt)$/] > Literal[value=/[A-Za-z]{2,}/]",
          message:
            "Literal UI attribute text is not allowed here; use useTranslations (R07-12).",
        },
      ],
    },
  },
]);

export default eslintConfig;
