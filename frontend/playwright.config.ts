import { defineConfig, devices } from '@playwright/test';

// AWS UAT supplies the deployed HTTPS origin; ordinary CI uses the offline
// handler and SQLite. Neither target changes the synthetic-only test payloads.
const externalURL = process.env.MERISMOS_UI_URL?.trim();

export default defineConfig({
  testDir: './e2e', timeout: 60_000, expect: { timeout: 15_000 },
  fullyParallel: false, retries: 0, workers: 1, maxFailures: 2,
  reporter: [['list'], ['junit', { outputFile: 'test-results/e2e.xml' }], ['html', { open: 'never' }]],
  use: { baseURL: externalURL || 'http://127.0.0.1:4173', trace: 'on', screenshot: 'on', video: 'retain-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: {width: 1440, height: 1000} } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }],
  webServer: externalURL ? undefined : [
    { command: 'python ../tests/http_server.py', url: 'http://127.0.0.1:8765/api/workspace', timeout: 30_000, reuseExistingServer: false },
    { command: 'npm run preview', url: 'http://127.0.0.1:4173', timeout: 30_000, reuseExistingServer: false },
  ],
});
