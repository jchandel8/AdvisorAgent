import { defineConfig, devices } from '@playwright/test';

// Run with: docker compose --profile e2e run --rm e2e
// E2E_AUTH=demo (default) uses the local demo picker; E2E_AUTH=cognito signs in through Cognito.
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'http://localhost:4200',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
