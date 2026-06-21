import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

// Flat-config ESLint for the Next.js static-export web app. Replaces the
// deprecated, interactive `next lint`. Kept lean and version-stable: ESLint 9 +
// typescript-eslint + eslint-plugin-react-hooks, without eslint-config-next
// (its eslint-plugin-react tree is incompatible with the current ESLint 10 line,
// and this repo only needs the core JS + TypeScript + React-hooks correctness
// rules). Runs non-interactively and exits non-zero only on errors.
export default tseslint.config(
  {
    ignores: [
      ".next/**",
      "out/**",
      "node_modules/**",
      "next-env.d.ts",
      "playwright-report/**",
      "test-results/**",
      "coverage/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  reactHooks.configs["recommended-latest"],
  {
    files: ["**/*.{ts,tsx,mjs,cjs,js}"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      // Allow intentionally-unused args/vars when prefixed with `_`.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
