/// <reference types="vitest" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Unit/component tests for the Next app. The Playwright browser specs under
// e2e/ are excluded (they run against the bundled production static UI, not
// jsdom). `@` resolves to the app root, matching tsconfig paths.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/__tests__/**/*.{test,spec}.{ts,tsx}", "**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", ".next/**", "out/**"],
  },
});
