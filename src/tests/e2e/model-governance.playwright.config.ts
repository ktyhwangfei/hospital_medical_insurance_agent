import { defineConfig } from '@playwright/test';

import baseConfig from './playwright.config';

const E2E_MODEL_GOVERNANCE_MASTER_KEY = 'MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=';
const E2E_BACKEND_URL = 'http://127.0.0.1:8000';
const E2E_PORTAL_URL = 'http://127.0.0.1:3000';

export default defineConfig({
  ...baseConfig,
  testMatch: ['flows/portal/model-governance.flow.ts'],
  testIgnore: [],
  retries: process.env.CI ? 2 : 1,
  use: {
    ...baseConfig.use,
    baseURL: E2E_PORTAL_URL,
  },
  webServer: [
    {
      command: 'uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory',
      url: `${E2E_BACKEND_URL}/health`,
      reuseExistingServer: false,
      timeout: 30000,
      cwd: '../../..',
      env: {
        ...process.env,
        SKILL_CONTROL_DEV_MODE: '1',
        MODEL_GOVERNANCE_DEV_MODE: '1',
        MODEL_GOVERNANCE_ENV: 'dev',
        // 仅供本地 E2E 加密临时治理凭据；外部显式配置始终优先。
        MODEL_GOVERNANCE_MASTER_KEY: process.env.MODEL_GOVERNANCE_MASTER_KEY ?? E2E_MODEL_GOVERNANCE_MASTER_KEY,
        USE_MEMORY_STORAGE: '1',
      },
    },
    {
      command: 'npm run dev',
      url: E2E_PORTAL_URL,
      cwd: '../../apps/portal',
      reuseExistingServer: false,
      env: {
        ...process.env,
        PORT: '3000',
        NEXT_PUBLIC_API_BASE_URL: E2E_BACKEND_URL,
      },
    },
  ],
});
