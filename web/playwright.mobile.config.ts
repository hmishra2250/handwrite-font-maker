import { defineConfig } from '@playwright/test';
import { readFileSync } from 'node:fs';

const preview = JSON.parse(readFileSync('../.alpha/mobile-preview.json', 'utf8')) as { origin: string };
if (!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(preview.origin)) throw new Error('Start scripts/alpha_mobile.py to obtain the test HTTPS origin.');

export default defineConfig({
  testDir: './e2e-mobile', timeout: 180_000, workers: 1, retries: 0,
  use: {
    baseURL: preview.origin, headless: true, trace: 'off',
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    permissions: ['camera'],
    launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
