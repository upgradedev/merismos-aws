import { defineConfig, devices } from '@playwright/test';

const externalURL = process.env.MERISMOS_UI_URL?.trim();
export default defineConfig({
  testDir: './proof-tests', timeout: 30_000, expect: { timeout: 15_000 },
  fullyParallel: false, retries: 0, workers: 1,
  // These counts never enter acceptance_receipt.py's product e2e.xml input.
  outputDir: 'proof-test-results',
  reporter: [['list'], ['junit', { outputFile: 'proof-test-results/proof-junit.xml' }],
    ['html', { outputFolder: 'proof-playwright-report', open: 'never' }]],
  use: { baseURL: externalURL || 'http://127.0.0.1:4173', trace: 'on', screenshot: 'on', video: 'retain-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }],
  webServer: externalURL ? undefined : {
    command: 'npm run preview', url: 'http://127.0.0.1:4173', timeout: 30_000, reuseExistingServer: false,
  },
});
