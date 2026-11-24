/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8600" } },
  // vmThreads: one jsdom per worker instead of per file (8.8 s -> 3 s), files stay isolated
  test: { environment: "jsdom", pool: "vmThreads" },
});
