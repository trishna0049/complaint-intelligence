/**
 * End-to-end test config. Playwright starts its own API and web servers on separate ports with a
 * separate SQLite file (var/e2e.db) and the mock LLM, so a run never touches the demo database or
 * calls OpenAI. Requires the trained classifier (`.\scripts\dev.ps1 train`) and backend/.venv.
 */
import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const root = path.resolve(__dirname, "../..");
// Keep browser downloads inside the project (gitignored) rather than on the system drive.
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(root, ".pw-browsers");

const API_PORT = process.env.E2E_API_PORT ?? "18100";
const WEB_PORT = process.env.E2E_WEB_PORT ?? "15200";
const python = path.join(root, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: ".",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: path.join(root, "backend"),
      url: `http://localhost:${API_PORT}/api/health`,
      timeout: 180_000, // first start loads the Hugging Face sentiment model
      reuseExistingServer: false,
      env: {
        DATABASE_URL: `sqlite:///${path.join(root, "var", "e2e.db").replace(/\\/g, "/")}`,
        LLM_PROVIDER: "mock",
        OPENAI_API_KEY: "",
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
        HF_HOME: path.join(root, "ml", ".hf_cache"),
      },
    },
    {
      command: "npx vite",
      cwd: path.join(root, "frontend"),
      url: `http://localhost:${WEB_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
      // vite.config.ts reads these, so the dev proxy points at the e2e API.
      env: { API_PORT, WEB_PORT },
    },
  ],
});
