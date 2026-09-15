import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run preview -- --port 4173",
    env: {
      VITE_API_BASE_URL: "http://127.0.0.1:8000/api/v1",
    },
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});
