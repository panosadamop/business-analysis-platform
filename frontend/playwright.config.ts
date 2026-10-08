import { defineConfig, devices } from '@playwright/test'

/**
 * Browser end to end tests against a running deployment.
 *
 *   docker compose up -d && docker compose run --rm seed
 *   npx playwright test
 *
 * Point AIT_E2E_BASE_URL elsewhere to test another environment.
 */
const baseURL = process.env.AIT_E2E_BASE_URL ?? 'http://localhost:8080'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
})
