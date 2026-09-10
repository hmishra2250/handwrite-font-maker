import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:3003',
    headless: true,
  },
  webServer: {
    command: 'npx next dev --port 3003',
    env: { HANDWRITE_E2E: '1', DEPLOYMENT_MODE: 'local', WORKER_API_BASE_URL: '' },
    port: 3003,
    timeout: 30_000,
    reuseExistingServer: false,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
