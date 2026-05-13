import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './',
  testMatch: ['**/*.spec.ts', '**/*.flow.ts'],
  timeout: 60000,
  expect: {
    timeout: 15000,
  },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['html'],
    ['list'],
  ],
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'firefox',
      use: {
        ...devices['Desktop Firefox'],
      },
    },
    {
      name: 'webkit',
      use: {
        ...devices['Desktop Safari'],
      },
    },
  ],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory',
      port: 8000,
      reuseExistingServer: true,
      timeout: 30000,
      cwd: '../../..',
    },
    {
      command: 'npm run dev',
      port: 3000,
      cwd: '../../apps/portal',
      reuseExistingServer: true,
    },
    {
      command: 'npm run dev',
      port: 3001,
      cwd: '../../apps/admin',
      reuseExistingServer: true,
    },
    {
      command: 'npm run dev',
      port: 3002,
      cwd: '../../apps/embed',
      reuseExistingServer: true,
    },
  ],
});
