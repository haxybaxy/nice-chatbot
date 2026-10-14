import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    css: false,
    mockReset: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    // Reporting only — there is deliberately no `thresholds` block. Quality is enforced
    // structurally (the contract validator, knip, jscpd, `onUnhandledRequest: "error"`), not by
    // a percentage. Use the report to find untested surfaces, then decide by risk.
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "html", "json-summary"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/shared/api/generated/**",
        "src/test/**",
        "src/**/__tests__/**",
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/shared/components/ui/**",
        "src/**/types/**",
      ],
    },
  },
});
