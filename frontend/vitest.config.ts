import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({ plugins: [react()], test: {
  environment: 'jsdom', setupFiles: ['./src/test/setup.ts'],
  include: ['src/**/*.test.{ts,tsx}'],
  reporters: ['default', 'junit'], outputFile: { junit: 'test-results/unit.xml' },
  coverage: { provider: 'v8', include: ['src/**/*.{ts,tsx}'],
    exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/types.ts'],
    reporter: ['text', 'html', 'json-summary', 'lcov'],
    thresholds: { statements: 85, branches: 85, functions: 85, lines: 85 } },
} });
