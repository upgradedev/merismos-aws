import { defineConfig } from '@playwright/test';

if (process.env.GITHUB_ACTIONS !== 'true' || process.env.MERISMOS_OFFLINE_HTTP !== '1' || process.env.MERISMOS_UI_URL) throw new Error('Measurement is CI-only, loopback-only; external targets are forbidden.');

export default defineConfig({
  testDir: './measurement', timeout: 22 * 60_000, retries: 0, workers: 1, fullyParallel: false,
  expect: {timeout: 10_000}, forbidOnly: true,
  outputDir: 'test-results/source-measurement-playwright', reporter: [['list']],
  use: {browserName: 'chromium', trace: 'off', video: 'off', screenshot: 'off'},
  webServer: [
    {command: 'python ../tests/http_server.py', url: 'http://127.0.0.1:8765/api/workspace', timeout: 30_000, reuseExistingServer: false},
    {command: 'npm run preview', url: 'http://127.0.0.1:4173', timeout: 30_000, reuseExistingServer: false},
  ],
});
