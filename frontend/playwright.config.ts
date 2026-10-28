import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests run against an isolated backend (port 8001, database finance_e2e) started by
 * scripts/e2e-backend.ps1. They never touch the main database.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5174", trace: "retain-on-failure" },
  webServer: [
    {
      command: "powershell -ExecutionPolicy Bypass -File ../scripts/e2e-backend.ps1",
      url: "http://127.0.0.1:8001/api/health",
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "ignore",
    },
    {
      command: "npx vite --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      env: { API_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
