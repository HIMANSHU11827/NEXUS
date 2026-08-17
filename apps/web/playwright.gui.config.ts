import { defineConfig, devices } from '@playwright/test'

// Runner config kept inside gui/ so Node resolves @playwright/test from
// gui/node_modules. Tests live in ../tests/gui. Use the already-installed
// Chromium via PLAYWRIGHT_BROWSERS_PATH (see tests/gui/README.md).
export default defineConfig({
  testDir: '../tests/gui',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    actionTimeout: 15_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
