import { defineConfig } from '@playwright/test';

const webPort = Number(process.env.ALPHA_E2E_WEB_PORT ?? 3007);
const apiPort = Number(process.env.ALPHA_E2E_API_PORT ?? 8007);
const origin = `http://localhost:${webPort}`;
const apiOrigin = `http://127.0.0.1:${apiPort}`;

// Isolated real services and throwaway credentials. Never reuse a developer server.
export default defineConfig({
  testDir: './e2e-alpha',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  use: { baseURL: origin, headless: true, trace: 'retain-on-failure' },
  webServer: [
    { command: '../.venv/bin/python ../tests/serve_alpha_e2e.py', url: `${apiOrigin}/readyz`, timeout: 60_000, reuseExistingServer: false, gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 }, env: { ALPHA_E2E_API_PORT: String(apiPort) } },
    {
      command: `npx next dev --port ${webPort}`, url: origin, timeout: 60_000, reuseExistingServer: false, gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 },
      env: {
        DEPLOYMENT_MODE: 'private_alpha', SITE_URL: origin, HANDWRITE_ALPHA_E2E: '1',
        INTERNAL_API_KEY: 'e2e-only-internal-secret-do-not-deploy-123456',
        WORKER_API_BASE_URL: apiOrigin,
        SUPABASE_URL: '', SUPABASE_ANON_KEY: '', SUPABASE_SERVICE_ROLE_KEY: '',
      },
    },
  ],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
