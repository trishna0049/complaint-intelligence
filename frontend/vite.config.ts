/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  // Reads the repo-root .env so ports stay in one place.
  const env = loadEnv(mode, path.resolve(__dirname, ".."), "");
  const backendPort = env.API_PORT || "18000";
  return {
    plugins: [react()],
    resolve: { alias: { "@": path.resolve(__dirname, "src") } },
    server: {
      port: Number(env.WEB_PORT || 15173),
      strictPort: true,
      proxy: {
        "/api": { target: `http://localhost:${backendPort}`, changeOrigin: false },
      },
    },
    build: { sourcemap: false, chunkSizeWarningLimit: 900 },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
