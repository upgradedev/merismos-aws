import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', timeout: 60_000, expect: { timeout: 15_000 },
  fullyParallel: false, retries: 0, workers: 1,
  reporter: [['list'], ['junit', { outputFile: 'test-results/e2e.xml' }], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'on', screenshot: 'on', video: 'retain-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: {width: 1440, height: 1000} } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }],
  webServer: [
    { command: 'python ../tests/http_server.py', url: 'http://127.0.0.1:8765/api/workspace', timeout: 30_000, reuseExistingServer: false },
    { command: 'npm run preview', url: 'http://127.0.0.1:4173', timeout: 30_000, reuseExistingServer: false },
  ],
});
