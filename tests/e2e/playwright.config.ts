/**
 * End-to-end test config. Playwright starts its own API, event workers and web server on separate ports, against
 * a separate PostgreSQL database (complaints_e2e, wiped and migrated on every run), its own Kafka topics (prefix
 * "e2e", deleted and recreated on every run) and the mock LLM, so a run never touches the demo data or calls
 * OpenAI. Requires the Compose infrastructure (`.\scripts\dev.ps1 up`: Postgres, Redis, Kafka), the trained
 * classifier (`.\scripts\dev.ps1 train`) and backend/.venv.
 */
import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const root = path.resolve(__dirname, "../..");
// Keep browser downloads inside the project (gitignored) rather than on the system drive.
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(root, ".pw-browsers");

const API_PORT = process.env.E2E_API_PORT ?? "18100";
const WEB_PORT = process.env.E2E_WEB_PORT ?? "15200";
const python = path.join(root, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const PG = `${process.env.POSTGRES_USER ?? "complaint"}:${process.env.POSTGRES_PASSWORD ?? "complaint_dev_pw"}@localhost:${process.env.POSTGRES_PORT ?? "15432"}`;
const E2E_DB = process.env.E2E_DATABASE_URL ?? `postgresql+asyncpg://${PG}/complaints_e2e`;
const WORKERS_HEALTH_PORT = process.env.E2E_WORKERS_HEALTH_PORT ?? "18191";
const backendEnv = {
  DATABASE_URL: E2E_DB,
  REDIS_URL: process.env.E2E_REDIS_URL ?? `redis://localhost:${process.env.REDIS_PORT ?? "16379"}/14`,
  LLM_PROVIDER: "mock",
  OPENAI_API_KEY: "",
  CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
  HF_HOME: path.join(root, "ml", ".hf_cache"),
  EVENTS_MODE: "kafka",
  EVENTS_PREFIX: "e2e",
  KAFKA_BOOTSTRAP_SERVERS: process.env.E2E_KAFKA ?? `localhost:${process.env.KAFKA_PORT ?? "19092"}`,
  COPILOT_AUTO: "true",
};

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
      command: `"${python}" -m scripts.prepare_db --reset && "${python}" -m scripts.seed --agents-per-team 2 && "${python}" -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: path.join(root, "backend"),
      url: `http://localhost:${API_PORT}/api/v1/health`,
      timeout: 180_000, // first start loads the Hugging Face sentiment model
      reuseExistingServer: false,
      env: backendEnv,
    },
    {
      // Outbox relay + AI, LLM, SLA and notification workers on fresh "e2e.*" topics.
      command: `"${python}" -m app.workers.run topics --reset && "${python}" -m app.workers.run all --health-port ${WORKERS_HEALTH_PORT}`,
      cwd: path.join(root, "backend"),
      url: `http://localhost:${WORKERS_HEALTH_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: backendEnv,
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
