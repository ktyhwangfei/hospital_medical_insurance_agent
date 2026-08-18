import { defineConfig, devices } from '@playwright/test';

const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8000);
const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? 3000);

export default defineConfig({
  testDir: './',
  testMatch: ['**/*.spec.ts', '**/*.flow.ts'],
  testIgnore: ['flows/portal/model-governance.flow.ts'],
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
        ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
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
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVERS ? undefined : [
    {
      command: `uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port ${backendPort} --factory`,
      port: backendPort,
      reuseExistingServer: true,
      timeout: 30000,
      cwd: '../../..',
      env: {
        ...process.env,
        SKILL_CONTROL_DEV_MODE: '1',
        MODEL_GOVERNANCE_DEV_MODE: '1',
        USE_MEMORY_STORAGE: '1',
      },
    },
    {
      command: `npm run dev -- -p ${frontendPort}`,
      port: frontendPort,
      cwd: '../../apps/portal',
      reuseExistingServer: true,
    },
  ],
});
