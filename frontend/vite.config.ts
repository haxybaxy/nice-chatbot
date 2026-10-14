import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
    dedupe: ["react", "react-dom"],
  },
  server: {
    // 3000 is the one origin the backend allows by default (CORS_ORIGINS in backend/app/core/config.py),
    // so a fresh checkout talks to `just dev` in backend/ with no extra configuration.
    port: 3000,
    host: true,
  },
  build: {
    outDir: "dist",
  },
});
