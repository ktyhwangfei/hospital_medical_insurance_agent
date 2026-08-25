import { defineConfig } from '@playwright/test';

import baseConfig from './playwright.config';

export default defineConfig({
  ...baseConfig,
  testMatch: ['flows/portal/model-governance.flow.ts'],
  testIgnore: [],
  retries: process.env.CI ? 2 : 1,
});
